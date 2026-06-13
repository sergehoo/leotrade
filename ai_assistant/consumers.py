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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None
        self.session = None
        self.client_context = {}
        # Suivi du stream en cours — permet de sauvegarder en cas de déconnexion
        self._stream_msg = None        # AssistantMessage placeholder actif
        self._stream_text = ""         # texte accumulé pendant le stream
        self._stream_ctx  = {}         # context_snapshot du message en cours
        self._stream_t0   = 0.0        # timestamp début stream

    async def connect(self):
        user = self.scope.get("user")
        if not user or user.is_anonymous:
            await self.close(code=4401)
            return

        self.user = user
        self._group = None

        await self.accept()

        # Route /ws/assistant/conversation/<id>/ → épingle la conversation
        pinned_id = (self.scope.get("url_route", {}).get("kwargs") or {}).get("conversation_id")
        if pinned_id:
            session = await self._get_owned_conversation(int(pinned_id))
            if session is None:
                await self.send_json({"type": "error", "message": "Conversation introuvable."})
                await self.close(code=4404)
                return
            self.session = session
        else:
            session = await self._get_or_create_session()

        await self._join_conversation_group(session.id)
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
        """La génération est détachée du WS (AssistantGenerationService) :
        elle continue côté serveur. On quitte simplement le groupe."""
        await self._leave_conversation_group()

    async def receive_json(self, content):
        msg_type = content.get("type", "chat")

        if msg_type == "chat":
            await self._handle_chat(content)
        elif msg_type == "action_confirm":
            await self._handle_action_confirm(content)
        elif msg_type == "action_reject":
            await self._handle_action_reject(content)
        elif msg_type == "context_update":
            ctx = content.get("context") or {}
            self.client_context = ctx
            # Si le client demande une nouvelle conversation pour ce contexte
            if ctx.get("_new_session"):
                await self._start_new_conversation(ctx)
            else:
                # Changement de contexte métier → bascule de conversation
                await self._switch_to_context(ctx)
        elif msg_type == "select_conversation":
            await self._select_conversation(content.get("id"))
        elif msg_type == "action_request_confirm":
            await self._handle_action_request_decision(content.get("request_id"), confirm=True)
        elif msg_type == "action_request_cancel":
            await self._handle_action_request_decision(content.get("request_id"), confirm=False)
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

        # Conversation du contexte métier courant (bascule si nécessaire)
        await self._switch_to_context(extra_ctx)
        session = self.session

        # 1. Persiste IMMÉDIATEMENT le message utilisateur (status=SAVED)
        user_msg = await self._save_message(session, "USER", user_text, {})
        await self._ensure_title(session, user_text)
        await self.send_json({"type": "user_saved", "id": user_msg.id})

        # 2. Moteur d'intentions : actions trading gérées DÉTERMINISTIQUEMENT
        #    (jamais par le LLM seul) ; GENERAL_CHAT → génération LLM détachée.
        handled = await self._handle_intent(session, user_text, extra_ctx)
        if handled:
            return

        # 3. Placeholder ASSISTANT (status=PARTIAL) — l'ID part tout de suite
        placeholder_msg = await self._save_message(
            session, "ASSISTANT", "", {}, status="PARTIAL",
        )

        # 3. Génération DÉTACHÉE : survit à la fermeture de la page / du WS.
        #    Les événements thinking/start/chunk/done arrivent via le groupe.
        from .services_generation import AssistantGenerationService
        AssistantGenerationService.launch(
            conversation_id=session.id,
            message_id=placeholder_msg.id,
            user_text=user_text,
            extra_ctx=extra_ctx,
        )

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
        """
        Paiement externe — Paystack par défaut, Stripe en fallback.
        Le client envoie {'type': 'quota_pay_stripe', 'plan': 'BASIC'}.
        """
        plan = content.get("plan", "BASIC")
        from django.conf import settings as djsettings
        base_url = getattr(djsettings, "SITE_URL", "http://127.0.0.1:8000")
        callback = f"{base_url}/assistant/quota/success/"

        # Paystack en priorité (Afrique), Stripe en fallback
        result = await sync_to_async(QuotaService.create_paystack_session)(
            user=self.user,
            plan=plan,
            callback_url=callback,
        )
        if result["ok"]:
            await self.send_json({
                "type": "quota_stripe_url",   # même type WS → même handler JS
                "url": result["url"],
                "plan": plan,
                "gateway": result.get("gateway", "paystack"),
            })
        else:
            await self.send_json({
                "type": "quota_payment_failed",
                "error": result.get("error"),
            })

    # ──────────────────────────────────────────────────────────────────────────
    # DB helpers & conversations
    # ──────────────────────────────────────────────────────────────────────────

    # ── Moteur d'intentions & actions ───────────────────────────────────────

    async def _handle_intent(self, session, user_text: str, extra_ctx: dict) -> bool:
        """Retourne True si le message a été traité par un outil/confirmation
        (le LLM n'est alors pas appelé)."""
        from .services_intent import AssistantIntentService, Intent

        detected = await sync_to_async(AssistantIntentService.detect)(user_text)

        if detected.intent == Intent.CONFIRM_TRADE_EXECUTION:
            return await self._confirm_pending_request(session)
        if detected.intent == Intent.CANCEL_ACTION:
            return await self._cancel_pending_request(session)

        from .services_tools import AssistantToolRegistry
        tool_name = AssistantToolRegistry.for_intent(detected.intent)
        if tool_name is None:
            return False  # GENERAL_CHAT → LLM

        result = await sync_to_async(AssistantToolRegistry.run)(
            tool_name, self.user, session, detected.entities,
        )
        await self._send_tool_result(session, result, intent=detected.intent)
        return True

    async def _confirm_pending_request(self, session) -> bool:
        from .services_actions import (
            AssistantActionService,
            AssistantConfirmationService,
        )

        pending = await sync_to_async(AssistantActionService.latest_pending)(
            self.user, session,
        )
        if pending is None:
            return False  # rien à confirmer → laisser le LLM répondre

        outcome = await sync_to_async(AssistantConfirmationService.confirm)(
            self.user, pending.id,
        )
        request = outcome.get("request")
        reply = outcome.get("message") or (
            "✅ Action exécutée." if outcome.get("ok") else "⚠ Échec de l'action."
        )
        await self._send_tool_result(session, {
            "ok": outcome.get("ok", False),
            "reply": reply,
            "action_request": (
                AssistantActionService.serialize(request) if request else None
            ),
            "data": {},
        }, intent="CONFIRM_TRADE_EXECUTION")
        return True

    async def _cancel_pending_request(self, session) -> bool:
        from .services_actions import (
            AssistantActionService,
            AssistantConfirmationService,
        )

        pending = await sync_to_async(AssistantActionService.latest_pending)(
            self.user, session,
        )
        if pending is None:
            return False

        outcome = await sync_to_async(AssistantConfirmationService.cancel)(
            self.user, pending.id,
        )
        request = outcome.get("request")
        await self._send_tool_result(session, {
            "ok": outcome.get("ok", False),
            "reply": outcome.get("message", "Action annulée."),
            "action_request": (
                AssistantActionService.serialize(request) if request else None
            ),
            "data": {},
        }, intent="CANCEL_ACTION")
        return True

    async def _handle_action_request_decision(self, request_id, confirm: bool):
        """Boutons Confirmer / Annuler des cartes d'action."""
        if not request_id:
            return
        from .services_actions import (
            AssistantActionService,
            AssistantConfirmationService,
        )

        fn = (AssistantConfirmationService.confirm if confirm
              else AssistantConfirmationService.cancel)
        outcome = await sync_to_async(fn)(self.user, int(request_id))
        request = outcome.get("request")
        await self._send_tool_result(self.session, {
            "ok": outcome.get("ok", False),
            "reply": outcome.get("message", ""),
            "action_request": (
                AssistantActionService.serialize(request) if request else None
            ),
            "data": {},
        }, intent="CONFIRM_TRADE_EXECUTION" if confirm else "CANCEL_ACTION")

    async def _send_tool_result(self, session, result: dict, intent: str):
        """Persiste la réponse outil comme message ASSISTANT + envoie au client."""
        reply = result.get("reply") or ("✅ Fait." if result.get("ok") else "⚠ Échec.")
        msg = await self._save_message(session, "ASSISTANT", reply, {"intent": intent})
        await self.send_json({"type": "start", "id": msg.id})
        await self.send_json({
            "type": "done",
            "id": msg.id,
            "status": "SAVED",
            "clean_content": reply,
            "actions": [],
            "action_request": result.get("action_request"),
            "quota": None,
            "meta": {"intent": intent, "tool_ok": result.get("ok", False)},
        })

    # ── Groupes channel-layer (un par conversation) ────────────────────────

    async def _join_conversation_group(self, conversation_id: int):
        from .services_generation import conversation_group
        await self._leave_conversation_group()
        group = conversation_group(conversation_id)
        try:
            await self.channel_layer.group_add(group, self.channel_name)
            self._group = group
        except Exception:
            log.warning("assistant.group_add_failed conv=%s", conversation_id)

    async def _leave_conversation_group(self):
        group = getattr(self, "_group", None)
        if group:
            try:
                await self.channel_layer.group_discard(group, self.channel_name)
            except Exception:
                pass
            self._group = None

    async def assistant_stream(self, event):
        """Relai des événements de génération (thinking/start/chunk/done)."""
        await self.send_json(event.get("data") or {})

    # ── Sélection / bascule de conversation ────────────────────────────────

    async def _switch_to_context(self, extra_ctx: dict):
        """Bascule sur la conversation du contexte métier si elle diffère."""
        from .services_conversation import ConversationService

        target = await sync_to_async(ConversationService.get_or_create_for_context)(
            self.user, extra_ctx,
        )
        if getattr(self, "session", None) is None or target.id != self.session.id:
            self.session = target
            await self._join_conversation_group(target.id)
            history = await self._load_history(target)
            await self.send_json({
                "type": "session",
                "session_id": target.id,
                "context_type": target.context_type,
                "context_id": target.context_id,
                "title": target.title,
                "history": history,
            })
        return self.session

    async def _select_conversation(self, conversation_id):
        """Reprise explicite d'une conversation (centre des conversations)."""
        if not conversation_id:
            return
        session = await self._get_owned_conversation(int(conversation_id))
        if session is None:
            await self.send_json({"type": "error", "message": "Conversation introuvable."})
            return
        self.session = session
        await self._join_conversation_group(session.id)
        history = await self._load_history(session)
        await self.send_json({
            "type": "session",
            "session_id": session.id,
            "context_type": session.context_type,
            "context_id": session.context_id,
            "title": session.title,
            "history": history,
        })

    async def _start_new_conversation(self, extra_ctx: dict):
        from .services_conversation import ConversationService

        session = await sync_to_async(ConversationService.start_new)(self.user, extra_ctx)
        self.session = session
        await self._join_conversation_group(session.id)
        await self.send_json({
            "type": "session",
            "session_id": session.id,
            "context_type": session.context_type,
            "context_id": session.context_id,
            "title": session.title,
            "history": [],
        })

    @sync_to_async
    def _get_owned_conversation(self, conversation_id: int):
        from .services_conversation import ConversationService
        return ConversationService.get_owned(self.user, conversation_id)

    @sync_to_async
    def _get_or_create_session(self, page: str | None = None, meta: dict | None = None):
        from .services_conversation import ConversationService

        ctx = dict(meta or {})
        if page:
            ctx.setdefault("page", page)
        session = ConversationService.get_or_create_for_context(self.user, ctx)
        self.session = session
        return session

    @sync_to_async
    def _ensure_title(self, session, first_message: str):
        session.ensure_title(first_message)

    @sync_to_async
    def _load_history(self, session) -> list[dict]:
        # On charge tous les messages : les messages vides (placeholders non finalisés)
        # seront affichés côté client avec un texte de substitution "[réponse incomplète]".
        msgs = session.messages.order_by("-created_at")[:MAX_HISTORY_TURNS * 2]
        result = []
        for m in reversed(list(msgs)):
            entry = {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "status": m.status,
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
    def _save_message(self, session, role: str, content: str, ctx: dict,
                      status: str = "SAVED"):
        from .models import AssistantMessage
        return AssistantMessage.objects.create(
            conversation=session,
            role=role,
            content=content,
            context_snapshot=ctx,
            status=status,
        )

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
