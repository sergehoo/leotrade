"""
Moteur de génération IA détaché du WebSocket.

Principe : quand l'utilisateur envoie un message, le consumer persiste le
message USER + un placeholder ASSISTANT (status=PARTIAL) puis lance la
génération dans une tâche asyncio **indépendante de la connexion WS**.

Garanties :
  - L'utilisateur ferme la page / perd la connexion → la génération CONTINUE
    côté serveur ; à son retour, l'historique contient la réponse complète.
  - Le contenu est sauvegardé PROGRESSIVEMENT en base (status=PARTIAL) :
    même un crash serveur ne perd que les derniers ~800 ms de texte.
  - Fin normale → status=SAVED ; échec moteur IA → status=FAILED avec le
    contenu partiel conservé et l'erreur journalisée.
  - Les chunks sont diffusés au groupe channel-layer `assistant_conv_{id}` :
    toute connexion WS (reconnexion incluse) reçoit le flux en cours.
"""

from __future__ import annotations

import asyncio
import logging
import time

from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer

log = logging.getLogger("leotrade.ai_assistant.generation")

# Fenêtre d'historique envoyée au LLM
MAX_HISTORY_TURNS = 10

# Persistance progressive : flush en base au plus tôt des deux seuils
FLUSH_INTERVAL_SECONDS = 0.8
FLUSH_MIN_CHARS = 400


def conversation_group(conversation_id: int) -> str:
    return f"assistant_conv_{conversation_id}"


class AssistantGenerationService:
    # Messages en cours de génération dans CE process (anti-duplication)
    _running: set[int] = set()

    # ------------------------------------------------------------------
    # Lancement
    # ------------------------------------------------------------------
    @classmethod
    def launch(cls, conversation_id: int, message_id: int, user_text: str,
               extra_ctx: dict | None = None) -> bool:
        """Démarre la génération en tâche de fond. Retourne False si une
        génération est déjà en cours pour ce message."""
        if message_id in cls._running:
            return False
        cls._running.add(message_id)
        task = asyncio.get_running_loop().create_task(
            cls._run_safe(conversation_id, message_id, user_text, extra_ctx or {})
        )
        # Référence gardée par le set _running ; la tâche se nettoie elle-même.
        task.add_done_callback(lambda _t: cls._running.discard(message_id))
        return True

    @classmethod
    async def _run_safe(cls, conversation_id, message_id, user_text, extra_ctx):
        try:
            await cls._run(conversation_id, message_id, user_text, extra_ctx)
        except Exception:
            log.exception(
                "generation.crashed conversation=%s message=%s",
                conversation_id, message_id,
            )
            await cls._mark_failed(message_id, "internal_error")
            await cls._broadcast(conversation_id, {
                "type": "done", "id": message_id,
                "status": "FAILED",
                "clean_content": None, "actions": [], "quota": None,
                "meta": {"error": "internal_error"},
            })

    # ------------------------------------------------------------------
    # Boucle de génération
    # ------------------------------------------------------------------
    @classmethod
    async def _run(cls, conversation_id, message_id, user_text, extra_ctx):
        from .services import (
            ASSISTANT_SYSTEM_PROMPT,
            AssistantContextService,
            AssistantStreamService,
            QuotaService,
            _format_context_for_prompt,
            extract_actions,
        )

        conversation, message = await cls._load(conversation_id, message_id)
        if conversation is None or message is None:
            return
        user = await sync_to_async(lambda: conversation.user)()

        # Contexte live + historique → messages LLM
        live_ctx = await sync_to_async(AssistantContextService.build)(
            user=user, extra=extra_ctx,
        )
        context_text = _format_context_for_prompt(live_ctx)
        lm_messages = await cls._build_lm_messages(
            conversation, message_id, user_text, context_text,
        )

        await cls._broadcast(conversation_id, {"type": "thinking"})
        await cls._broadcast(conversation_id, {"type": "start", "id": message_id})

        t0 = time.monotonic()
        full_text = ""
        last_flush_t = t0
        last_flush_len = 0
        stream_ok = False

        try:
            async for chunk in AssistantStreamService.stream(
                messages=lm_messages,
                system_prompt=ASSISTANT_SYSTEM_PROMPT,
            ):
                full_text += chunk
                await cls._broadcast(conversation_id, {
                    "type": "chunk", "text": chunk, "id": message_id,
                    "acc_len": len(full_text),
                })

                # Persistance progressive — aucun texte perdu même sur crash
                now = time.monotonic()
                if (now - last_flush_t >= FLUSH_INTERVAL_SECONDS
                        and len(full_text) - last_flush_len >= FLUSH_MIN_CHARS):
                    await cls._flush_partial(message_id, full_text, live_ctx)
                    last_flush_t, last_flush_len = now, len(full_text)
            stream_ok = True
        except Exception as exc:
            log.exception("generation.stream_error conversation=%s err=%s",
                          conversation_id, exc)

        latency_ms = int((time.monotonic() - t0) * 1000)
        clean_text, raw_actions = extract_actions(full_text)

        if stream_ok:
            saved_actions = await cls._finalize(
                message_id, clean_text or full_text, live_ctx, latency_ms,
                raw_actions, status="SAVED",
            )
            quota = await sync_to_async(QuotaService.get_or_create)(user)
            await sync_to_async(quota.consume)()
            quota_payload = await sync_to_async(cls._serialize_quota)(quota)
        else:
            note = "\n\n*[Le moteur IA a été interrompu — réponse partielle conservée.]*"
            saved_actions = await cls._finalize(
                message_id,
                (clean_text or full_text) + (note if full_text else ""),
                live_ctx, latency_ms, raw_actions,
                status="FAILED",
                error="provider_stream_error",
            )
            quota_payload = None

        await cls._broadcast(conversation_id, {
            "type": "done",
            "id": message_id,
            "status": "SAVED" if stream_ok else "FAILED",
            "clean_content": clean_text or full_text,
            "actions": saved_actions,
            "quota": quota_payload,
            "meta": {
                "latency_ms": latency_ms,
                "has_kill_switch": (live_ctx.get("risk") or {}).get("kill_switch_active", False),
            },
        })

    # ------------------------------------------------------------------
    # Channel layer
    # ------------------------------------------------------------------
    @staticmethod
    async def _broadcast(conversation_id: int, data: dict):
        try:
            layer = get_channel_layer()
            if layer is not None:
                await layer.group_send(
                    conversation_group(conversation_id),
                    {"type": "assistant.stream", "data": data},
                )
        except Exception:
            # Le temps réel est best-effort : la vérité est en base.
            log.warning("generation.broadcast_failed conversation=%s", conversation_id)

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------
    @staticmethod
    @sync_to_async
    def _load(conversation_id, message_id):
        from .models import AssistantConversation, AssistantMessage

        conversation = (
            AssistantConversation.objects
            .select_related("user")
            .filter(pk=conversation_id).first()
        )
        message = AssistantMessage.objects.filter(
            pk=message_id, conversation_id=conversation_id,
        ).first()
        return conversation, message

    @staticmethod
    @sync_to_async
    def _build_lm_messages(conversation, current_msg_id, user_text, context_text):
        history = list(
            conversation.messages
            .filter(role__in=["USER", "ASSISTANT"])
            .exclude(content="")
            .exclude(pk=current_msg_id)
            .order_by("-created_at")[:MAX_HISTORY_TURNS * 2]
        )
        lm = [
            {"role": "user" if m.role == "USER" else "assistant", "content": m.content}
            for m in reversed(history)
        ]
        # Le dernier message de l'historique est déjà le message USER persisté ;
        # on le remplace par la version enrichie du contexte live.
        if lm and lm[-1]["role"] == "user" and lm[-1]["content"] == user_text:
            lm.pop()
        lm.append({
            "role": "user",
            "content": f"{context_text}\n\nMESSAGE UTILISATEUR : {user_text}",
        })
        return lm

    @staticmethod
    @sync_to_async
    def _flush_partial(message_id, content, ctx):
        from .models import AssistantMessage

        AssistantMessage.objects.filter(pk=message_id).update(
            content=content, status=AssistantMessage.STATUS_PARTIAL,
            context_snapshot=ctx,
        )

    @staticmethod
    @sync_to_async
    def _mark_failed(message_id, error: str):
        from .models import AssistantMessage

        AssistantMessage.objects.filter(pk=message_id).update(
            status=AssistantMessage.STATUS_FAILED, error_message=error,
        )

    @staticmethod
    @sync_to_async
    def _finalize(message_id, content, ctx, latency_ms, raw_actions,
                  status="SAVED", error=""):
        from .models import AssistantAction, AssistantMessage

        message = AssistantMessage.objects.filter(pk=message_id).first()
        if message is None:
            return []
        message.content = content
        message.context_snapshot = ctx
        message.latency_ms = latency_ms
        message.status = status
        message.error_message = error
        message.save(update_fields=[
            "content", "context_snapshot", "latency_ms",
            "status", "error_message", "updated_at",
        ])

        saved = []
        for action_data in raw_actions or []:
            action_type = action_data.get("type", "INFO")
            if action_type not in dict(AssistantAction.ACTION_TYPE_CHOICES):
                action_type = AssistantAction.TYPE_INFO
            action = AssistantAction.objects.create(
                message=message,
                action_type=action_type,
                parameters={k: v for k, v in action_data.items() if k != "type"},
                rationale=action_data.get("rationale", ""),
                status=AssistantAction.STATUS_PROPOSED,
            )
            saved.append({
                "id": action.id, "type": action.action_type,
                "params": action.parameters, "status": action.status,
                "rationale": action.rationale,
            })
        return saved

    @staticmethod
    def _serialize_quota(quota):
        if quota is None:
            return None
        return {
            "plan": quota.plan,
            "used": quota.messages_used,
            "limit": quota.messages_limit,
            "remaining": quota.remaining,
            "usage_pct": quota.usage_pct,
            "exhausted": quota.is_exhausted,
        }
