"""
ai_assistant/consumers.py
==========================

WebSocket consumer pour le panel IA conversationnel LeoAI.

Protocole (JSON) :
  Client → Server :
    {"type": "chat",           "message": "...", "context": {...}}
    {"type": "action_confirm", "action_id": 42}
    {"type": "action_reject",  "action_id": 42}
    {"type": "context_update", "context": {"page": "positions", ...}}
    {"type": "history"}     ← charge l'historique de la session

  Server → Client :
    {"type": "session",   "session_id": 1, "history": [...]}
    {"type": "thinking"}  ← LeoAI commence à rédiger
    {"type": "chunk",     "text": "...", "id": <msg_id>}
    {"type": "done",      "id": <msg_id>, "actions": [...], "meta": {...}}
    {"type": "action_update", "action_id": ..., "status": "CONFIRMED"|"REJECTED"}
    {"type": "error",     "message": "..."}
"""
from __future__ import annotations

import json
import logging
import time
from decimal import Decimal

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.utils import timezone

from .services import (
    AssistantContextService,
    AssistantStreamService,
    QuotaService,
    ASSISTANT_SYSTEM_PROMPT,
    _format_context_for_prompt,
    extract_actions,
)

log = logging.getLogger("leotrade.ai_assistant.consumer")

# Historique de conversation envoyé au LLM (sliding window)
MAX_HISTORY_TURNS = 10  # N derniers échanges user+assistant


class AssistantConsumer(AsyncJsonWebsocketConsumer):

    async def connect(self):
        user = self.scope.get("user")
        if not user or user.is_anonymous:
            await self.close(code=4401)
            return

        self.user = user
        self.session = None
        self.client_context = {}  # contexte envoyé par le client (page, ids…)

        await self.accept()

        # Création ou reprise de session
        session = await self._get_or_create_session()
        history = await self._load_history(session)

        # Snapshot quota pour initialiser l'UI
        quota_info = await sync_to_async(QuotaService.check)(user)
        quota_obj = quota_info.get("quota")

        await self.send_json({
            "type": "session",
            "session_id": session.id,
            "history": history,
            "quota": _serialize_quota(quota_obj),
        })

    async def disconnect(self, close_code):
        pass

    async def receive_json(self, content):
        msg_type = content.get("type", "chat")

        if msg_type == "chat":
            await self._handle_chat(content)
        elif msg_type == "action_confirm":
            await self._handle_action_confirm(content)
        elif msg_type == "action_reject":
            await self._handle_action_reject(content)
        elif msg_type == "context_update":
            self.client_context = content.get("context") or {}
        elif msg_type == "history":
            session = await self._get_or_create_session()
            history = await self._load_history(session)
            await self.send_json({"type": "history", "messages": history})
        elif msg_type == "quota_pay_wallet":
            await self._handle_quota_pay_wallet(content)
        elif msg_type == "quota_pay_stripe":
            await self._handle_quota_pay_stripe(content)
        else:
            await self.send_json({"type": "error", "message": f"Type inconnu : {msg_type}"})

    # ──────────────────────────────────────────────────────────────────────────
    # Handlers
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_chat(self, content: dict):
        user_text = (content.get("message") or "").strip()
        if not user_text:
            return

        # ── Vérification quota ─────────────────────────────────────────────
        quota_check = await sync_to_async(QuotaService.check)(self.user)
        if not quota_check["ok"]:
            quota_obj = quota_check.get("quota")
            await self.send_json({
                "type": "quota_exceeded",
                "quota": _serialize_quota(quota_obj),
                "plans": quota_check.get("plans", []),
                "reason": quota_check.get("reason", "exhausted"),
            })
            return

        # Fusionne les contextes client
        extra_ctx = {**self.client_context, **(content.get("context") or {})}

        session = await self._get_or_create_session(
            page=extra_ctx.get("page"),
            meta=extra_ctx,
        )

        # 1. Persiste le message utilisateur
        user_msg = await self._save_message(session, "USER", user_text, {})

        # 2. Construit le contexte live
        live_ctx = await sync_to_async(AssistantContextService.build)(
            user=self.user,
            extra=extra_ctx,
        )
        context_text = _format_context_for_prompt(live_ctx)

        # 3. Construit l'historique conversationnel pour le LLM
        lm_messages = await self._build_lm_messages(session, user_text, context_text)

        # 4. Signal « en train de réfléchir »
        await self.send_json({"type": "thinking"})

        # 5. Stream la réponse
        t0 = time.monotonic()
        full_response = ""
        assistant_msg_id = None  # sera fixé après persistence

        # On crée d'abord un placeholder pour avoir l'ID
        placeholder_msg = await self._save_message(session, "ASSISTANT", "", live_ctx)
        assistant_msg_id = placeholder_msg.id
        await self.send_json({"type": "start", "id": assistant_msg_id})

        try:
            async for chunk in AssistantStreamService.stream(
                messages=lm_messages,
                system_prompt=ASSISTANT_SYSTEM_PROMPT,
            ):
                full_response += chunk
                await self.send_json({"type": "chunk", "text": chunk, "id": assistant_msg_id})
        except Exception as exc:
            log.exception("assistant.stream.error session=%s err=%s", session.id, exc)
            error_text = "\n\n⚠️ Erreur de communication avec le moteur IA. Veuillez réessayer."
            full_response += error_text
            await self.send_json({"type": "chunk", "text": error_text, "id": assistant_msg_id})

        latency_ms = int((time.monotonic() - t0) * 1000)

        # 6. Extraction des actions proposées
        clean_response, raw_actions = extract_actions(full_response)

        # 7. Persiste le message complet + actions
        saved_actions = await self._finalize_assistant_message(
            msg=placeholder_msg,
            content=clean_response,
            context_snapshot=live_ctx,
            latency_ms=latency_ms,
            raw_actions=raw_actions,
        )

        # 8. Consommer 1 message du quota (après succès du stream)
        updated_quota = await sync_to_async(QuotaService.get_or_create)(self.user)
        await sync_to_async(updated_quota.consume)()

        # 9. Envoie le signal de fin + texte nettoyé + actions + quota mis à jour
        # clean_content permet au client de remplacer le texte brut (qui
        # contenait les marqueurs <<<ACTION>>>) par le texte final épuré.
        await self.send_json({
            "type": "done",
            "id": assistant_msg_id,
            "clean_content": clean_response,
            "actions": saved_actions,
            "quota": _serialize_quota(updated_quota),
            "meta": {
                "latency_ms": latency_ms,
                "has_kill_switch": live_ctx.get("risk", {}).get("kill_switch_active", False),
            },
        })

    async def _handle_action_confirm(self, content: dict):
        action_id = content.get("action_id")
        if not action_id:
            return

        result = await self._confirm_action(action_id)
        await self.send_json({
            "type": "action_update",
            "action_id": action_id,
            "status": "CONFIRMED",
            "result": result,
        })

    async def _handle_action_reject(self, content: dict):
        action_id = content.get("action_id")
        if not action_id:
            return

        await self._reject_action(action_id)
        await self.send_json({
            "type": "action_update",
            "action_id": action_id,
            "status": "REJECTED",
        })

    async def _handle_quota_pay_wallet(self, content: dict):
        """Payer un plan LeoAI via débit du portefeuille."""
        plan = content.get("plan", "BASIC")
        result = await sync_to_async(QuotaService.pay_with_wallet)(self.user, plan)
        if result["ok"]:
            quota = await sync_to_async(QuotaService.get_or_create)(self.user)
            await self.send_json({
                "type": "quota_updated",
                "quota": _serialize_quota(quota),
                "message": f"✅ Plan {plan} activé — {quota.messages_limit} messages disponibles !",
            })
        else:
            await self.send_json({
                "type": "quota_payment_failed",
                "error": result.get("error"),
                "insufficient_funds": result.get("insufficient_funds", False),
            })

    async def _handle_quota_pay_stripe(self, content: dict):
        """Créer une session Stripe Checkout pour l'achat d'un plan."""
        plan = content.get("plan", "BASIC")
        from django.conf import settings as djsettings
        base_url = getattr(djsettings, "SITE_URL", "http://127.0.0.1:8000")
        result = await sync_to_async(QuotaService.create_stripe_session)(
            user=self.user,
            plan=plan,
            success_url=f"{base_url}/assistant/quota/success/",
            cancel_url=f"{base_url}/assistant/quota/cancel/",
        )
        if result["ok"]:
            await self.send_json({
                "type": "quota_stripe_url",
                "url": result["url"],
                "plan": plan,
            })
        else:
            await self.send_json({
                "type": "quota_payment_failed",
                "error": result.get("error"),
            })

    # ──────────────────────────────────────────────────────────────────────────
    # DB helpers (sync_to_async)
    # ──────────────────────────────────────────────────────────────────────────

    @sync_to_async
    def _get_or_create_session(self, page: str | None = None, meta: dict | None = None):
        from .models import AssistantSession
        from portfolio.models import Portfolio

        portfolio = (
            Portfolio.objects
            .filter(user=self.user, is_active=True)
            .order_by("-is_default")
            .first()
        )

        session, created = AssistantSession.objects.get_or_create(
            user=self.user,
            is_active=True,
            defaults={
                "portfolio": portfolio,
                "page_context": page or "dashboard",
                "meta": meta or {},
            },
        )

        if not created and page and session.page_context != page:
            session.page_context = page
            session.meta = {**(session.meta or {}), **(meta or {})}
            session.save(update_fields=["page_context", "meta", "updated_at"])

        self.session = session
        return session

    @sync_to_async
    def _load_history(self, session) -> list[dict]:
        # On exclut les messages vides (placeholders créés pendant le streaming
        # et jamais finalisés, ex : déconnexion en cours de génération).
        msgs = session.messages.exclude(content="").order_by("-created_at")[:MAX_HISTORY_TURNS * 2]
        result = []
        for m in reversed(list(msgs)):
            entry = {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat(),
            }
            if m.role == "ASSISTANT":
                entry["provider"] = m.provider
                entry["latency_ms"] = m.latency_ms
                # Actions liées à ce message
                entry["actions"] = [
                    {
                        "id": a.id,
                        "type": a.action_type,
                        "params": a.parameters,
                        "status": a.status,
                        "rationale": a.rationale,
                    }
                    for a in m.actions.all()
                ]
            result.append(entry)
        return result

    @sync_to_async
    def _save_message(self, session, role: str, content: str, ctx: dict):
        from .models import AssistantMessage
        return AssistantMessage.objects.create(
            session=session,
            role=role,
            content=content,
            context_snapshot=ctx,
        )

    @sync_to_async
    def _build_lm_messages(self, session, current_user_text: str, context_text: str) -> list[dict]:
        """
        Construit la liste de messages à envoyer au LLM.
        Format : [{"role": "user"|"assistant", "content": "..."}]
        On injecte le contexte live dans le premier message utilisateur.
        """
        history_msgs = list(
            session.messages
            .filter(role__in=["USER", "ASSISTANT"])
            .exclude(content="")
            .order_by("-created_at")
            [:(MAX_HISTORY_TURNS * 2)]
        )
        history_msgs = list(reversed(history_msgs))

        lm = []
        for m in history_msgs:
            role = "user" if m.role == "USER" else "assistant"
            lm.append({"role": role, "content": m.content})

        # Message utilisateur courant avec contexte live
        lm.append({
            "role": "user",
            "content": f"{context_text}\n\nMESSAGE UTILISATEUR : {current_user_text}",
        })
        return lm

    @sync_to_async
    def _finalize_assistant_message(
        self,
        msg,
        content: str,
        context_snapshot: dict,
        latency_ms: int,
        raw_actions: list[dict],
    ) -> list[dict]:
        from .models import AssistantAction

        msg.content = content
        msg.context_snapshot = context_snapshot
        msg.latency_ms = latency_ms
        msg.save(update_fields=["content", "context_snapshot", "latency_ms", "updated_at"])

        saved = []
        for action_data in raw_actions:
            action_type = action_data.get("type", "INFO")
            if action_type not in dict(AssistantAction.ACTION_TYPE_CHOICES):
                action_type = AssistantAction.TYPE_INFO
            action = AssistantAction.objects.create(
                message=msg,
                action_type=action_type,
                parameters={k: v for k, v in action_data.items() if k != "type"},
                rationale=action_data.get("rationale", ""),
                status=AssistantAction.STATUS_PROPOSED,
            )
            saved.append({
                "id": action.id,
                "type": action.action_type,
                "params": action.parameters,
                "status": action.status,
                "rationale": action.rationale,
            })
        return saved

    @sync_to_async
    def _confirm_action(self, action_id: int) -> dict:
        from .models import AssistantAction
        action = AssistantAction.objects.filter(
            pk=action_id,
            message__session__user=self.user,
        ).first()
        if not action:
            return {"error": "Action introuvable"}

        action.confirm()

        result: dict = {}

        # Draft d'ordre : on prépare les données pour le formulaire frontend
        if action.action_type == AssistantAction.TYPE_DRAFT_ORDER:
            result = {
                "redirect": "draft_order",
                "params": action.parameters,
            }
            action.mark_executed(result)

        return result

    @sync_to_async
    def _reject_action(self, action_id: int):
        from .models import AssistantAction
        action = AssistantAction.objects.filter(
            pk=action_id,
            message__session__user=self.user,
        ).first()
        if action:
            action.reject()


# ── Helpers module-level ──────────────────────────────────────────────────────

def _serialize_quota(quota) -> dict | None:
    """Sérialise un objet AIUserQuota en dict JSON-safe pour le WS."""
    if quota is None:
        return None
    return {
        "plan": quota.plan,
        "used": quota.messages_used,
        "limit": quota.messages_limit,
        "remaining": quota.remaining,
        "pct": quota.usage_pct,
        "exhausted": quota.is_exhausted,
        "plan_label": dict(quota.PLAN_CHOICES).get(quota.plan, quota.plan),
    }
