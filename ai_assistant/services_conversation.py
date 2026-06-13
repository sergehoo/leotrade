"""
ConversationService — gestion des conversations contextuelles.

Chaque objet métier (trade idea, position, ordre, portefeuille, broker,
signal, opportunité) possède sa conversation indépendante ; le dashboard
et l'assistant général ont la leur. La résolution se fait depuis le
contexte client (page + ids) envoyé par le frontend.
"""

from __future__ import annotations

import logging

from django.db.models import Count, Q

from .models import AssistantConversation, AssistantConversationParticipant

log = logging.getLogger("leotrade.ai_assistant.conversation")

# Clés de contexte client → (context_type)
_CONTEXT_ID_KEYS = [
    ("trade_idea_id", AssistantConversation.CONTEXT_TRADE_IDEA),
    ("idea_id", AssistantConversation.CONTEXT_TRADE_IDEA),
    ("position_id", AssistantConversation.CONTEXT_POSITION),
    ("order_id", AssistantConversation.CONTEXT_ORDER),
    ("portfolio_id", AssistantConversation.CONTEXT_PORTFOLIO),
    ("broker_account_id", AssistantConversation.CONTEXT_BROKER),
    ("broker_id", AssistantConversation.CONTEXT_BROKER),
    ("signal_id", AssistantConversation.CONTEXT_SIGNAL),
    ("opportunity_id", AssistantConversation.CONTEXT_OPPORTUNITY),
    ("recommendation_id", AssistantConversation.CONTEXT_OPPORTUNITY),
]

_PAGE_CONTEXT_TYPES = {
    "dashboard": AssistantConversation.CONTEXT_DASHBOARD,
}


class ConversationService:
    # ------------------------------------------------------------------
    # Résolution du contexte
    # ------------------------------------------------------------------
    @staticmethod
    def resolve_context(extra_ctx: dict | None) -> tuple[str, int | None]:
        """(context_type, context_id) depuis le contexte client."""
        ctx = extra_ctx or {}

        for key, context_type in _CONTEXT_ID_KEYS:
            raw = ctx.get(key)
            if raw in (None, "", 0, "0"):
                continue
            try:
                return context_type, int(raw)
            except (TypeError, ValueError):
                continue

        page = str(ctx.get("page") or "").strip().lower()
        if page in _PAGE_CONTEXT_TYPES:
            return _PAGE_CONTEXT_TYPES[page], None

        return AssistantConversation.CONTEXT_GENERAL, None

    # ------------------------------------------------------------------
    # Accès / création
    # ------------------------------------------------------------------
    @classmethod
    def get_or_create_for_context(cls, user, extra_ctx: dict | None = None,
                                  portfolio=None) -> AssistantConversation:
        """Conversation active du contexte (une par contexte, hors archivées)."""
        context_type, context_id = cls.resolve_context(extra_ctx)

        conversation = (
            AssistantConversation.objects
            .filter(
                user=user, context_type=context_type, context_id=context_id,
                archived=False, is_active=True,
            )
            .order_by("-updated_at")
            .first()
        )
        if conversation is None:
            if portfolio is None:
                from portfolio.models import Portfolio
                portfolio = (
                    Portfolio.objects
                    .filter(user=user, is_active=True)
                    .order_by("-is_default")
                    .first()
                )
            conversation = AssistantConversation.objects.create(
                user=user,
                portfolio=portfolio,
                context_type=context_type,
                context_id=context_id,
                page_context=str((extra_ctx or {}).get("page") or "dashboard")[:100],
                meta=extra_ctx or {},
            )
            AssistantConversationParticipant.objects.get_or_create(
                conversation=conversation, user=user,
                defaults={"role": AssistantConversationParticipant.ROLE_OWNER},
            )
        return conversation

    @staticmethod
    def get_owned(user, conversation_id: int) -> AssistantConversation | None:
        """Contrôle d'ownership strict : la conversation doit appartenir au user."""
        return AssistantConversation.objects.filter(
            pk=conversation_id, user=user,
        ).first()

    @staticmethod
    def start_new(user, extra_ctx: dict | None = None) -> AssistantConversation:
        """Archive la conversation active du contexte et en démarre une neuve."""
        context_type, context_id = ConversationService.resolve_context(extra_ctx)
        AssistantConversation.objects.filter(
            user=user, context_type=context_type, context_id=context_id,
            archived=False,
        ).update(archived=True)
        return ConversationService.get_or_create_for_context(user, extra_ctx)

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------
    @staticmethod
    def analytics(user=None) -> dict:
        """Statistiques réelles : conversations, messages, tokens, coût,
        taux d'erreur, latence moyenne. user=None → global (admin)."""
        from django.db.models import Avg, Sum

        from .models import AssistantMessage

        conversations = AssistantConversation.objects.all()
        messages = AssistantMessage.objects.all()
        if user is not None:
            conversations = conversations.filter(user=user)
            messages = messages.filter(conversation__user=user)

        assistant_msgs = messages.filter(role="ASSISTANT")
        agg = assistant_msgs.aggregate(
            total=Count("id"),
            failed=Count("id", filter=Q(status="FAILED")),
            partial=Count("id", filter=Q(status="PARTIAL")),
            tokens_in=Sum("tokens_in"),
            tokens_out=Sum("tokens_out"),
            cost_usd=Sum("cost_usd"),
            avg_latency_ms=Avg("latency_ms", filter=Q(latency_ms__gt=0)),
        )
        total = agg["total"] or 0

        per_model = list(
            assistant_msgs.exclude(model_name="")
            .values("provider", "model_name")
            .annotate(messages=Count("id"), cost=Sum("cost_usd"))
            .order_by("-messages")[:10]
        )

        return {
            "conversations": conversations.count(),
            "conversations_archived": conversations.filter(archived=True).count(),
            "messages_total": messages.count(),
            "assistant_messages": total,
            "failed_messages": agg["failed"] or 0,
            "partial_messages": agg["partial"] or 0,
            "error_rate": round((agg["failed"] or 0) / total, 4) if total else None,
            "tokens_in": agg["tokens_in"] or 0,
            "tokens_out": agg["tokens_out"] or 0,
            "cost_usd": str(agg["cost_usd"] or 0),
            "avg_latency_ms": round(agg["avg_latency_ms"]) if agg["avg_latency_ms"] else None,
            "per_model": per_model,
        }
