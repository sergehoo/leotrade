"""
Admin du chat persistant LeoAI : conversations, messages, statistiques
(tokens, coûts, erreurs IA, latence) et quotas.
"""

from django.contrib import admin
from django.db.models import Avg, Count, Q, Sum

from .models import (
    AIQuotaPayment,
    AIUserQuota,
    AssistantAction,
    AssistantAttachment,
    AssistantConversation,
    AssistantConversationParticipant,
    AssistantMessage,
)


class MessageInline(admin.TabularInline):
    model = AssistantMessage
    extra = 0
    can_delete = False
    fields = ("role", "status", "short_content", "provider", "tokens_in",
              "tokens_out", "cost_usd", "latency_ms", "created_at")
    readonly_fields = fields

    @admin.display(description="Contenu")
    def short_content(self, obj):
        return (obj.content or "")[:120]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(AssistantConversation)
class AssistantConversationAdmin(admin.ModelAdmin):
    list_display = (
        "id", "user", "title_display", "context_type", "context_id",
        "message_count", "total_cost", "archived", "updated_at",
    )
    list_filter = ("context_type", "archived", "is_active", "created_at")
    search_fields = ("title", "user__username", "user__email", "messages__content")
    date_hierarchy = "created_at"
    inlines = [MessageInline]
    readonly_fields = ("user", "portfolio", "page_context", "meta",
                       "created_at", "updated_at")

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related("user")
            .annotate(
                _message_count=Count("messages", distinct=True),
                _total_cost=Sum("messages__cost_usd"),
            )
        )

    @admin.display(description="Titre")
    def title_display(self, obj):
        return obj.title or obj.context_label

    @admin.display(description="Messages", ordering="_message_count")
    def message_count(self, obj):
        return obj._message_count

    @admin.display(description="Coût IA ($)", ordering="_total_cost")
    def total_cost(self, obj):
        return f"{obj._total_cost or 0:.4f}"


@admin.register(AssistantMessage)
class AssistantMessageAdmin(admin.ModelAdmin):
    list_display = (
        "id", "conversation", "role", "status", "provider", "model_name",
        "tokens_in", "tokens_out", "cost_usd", "latency_ms", "created_at",
    )
    list_filter = ("role", "status", "provider", "model_name", "created_at")
    search_fields = ("content", "conversation__title", "conversation__user__username")
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in AssistantMessage._meta.fields]

    def changelist_view(self, request, extra_context=None):
        """Statistiques globales en tête de liste : tokens, coût, erreurs, latence."""
        agg = AssistantMessage.objects.filter(role="ASSISTANT").aggregate(
            total=Count("id"),
            failed=Count("id", filter=Q(status="FAILED")),
            partial=Count("id", filter=Q(status="PARTIAL")),
            tokens_in=Sum("tokens_in"),
            tokens_out=Sum("tokens_out"),
            cost=Sum("cost_usd"),
            latency=Avg("latency_ms", filter=Q(latency_ms__gt=0)),
        )
        total = agg["total"] or 0
        extra_context = extra_context or {}
        extra_context["title"] = (
            f"Messages IA — {total} réponses · "
            f"{agg['failed'] or 0} échecs ({(agg['failed'] or 0) / total:.1%} ) · "
            f"{(agg['tokens_in'] or 0) + (agg['tokens_out'] or 0):,} tokens · "
            f"${agg['cost'] or 0:.2f} · "
            f"latence moy. {round(agg['latency'] or 0)} ms"
            if total else "Messages IA"
        )
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(AssistantAction)
class AssistantActionAdmin(admin.ModelAdmin):
    list_display = ("id", "message", "action_type", "status", "created_at")
    list_filter = ("action_type", "status", "created_at")
    search_fields = ("rationale",)


@admin.register(AssistantConversationParticipant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ("conversation", "user", "role", "joined_at")
    list_filter = ("role",)


@admin.register(AssistantAttachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ("filename", "conversation", "user", "size_bytes", "created_at")
    search_fields = ("filename",)


@admin.register(AIUserQuota)
class AIUserQuotaAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "messages_used", "messages_limit",
                    "total_spent_usd", "is_suspended", "updated_at")
    list_filter = ("plan", "is_suspended")
    search_fields = ("user__username", "user__email")


@admin.register(AIQuotaPayment)
class AIQuotaPaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "quota", "plan", "amount_usd", "method", "status", "created_at")
    list_filter = ("method", "status", "plan")
