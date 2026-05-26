from django.contrib import admin

from .models import AIDecisionLog


@admin.register(AIDecisionLog)
class AIDecisionLogAdmin(admin.ModelAdmin):
    list_display = (
        "id", "created_at", "symbol", "decision", "confidence",
        "provider", "model_name", "fallback_used", "latency_ms", "cost_usd",
    )
    list_filter = ("provider", "decision", "fallback_used", "model_name")
    search_fields = ("symbol", "rationale", "user__username", "user__email")
    date_hierarchy = "created_at"
    readonly_fields = (
        "created_at", "raw_response", "prompt_inputs",
        "latency_ms", "tokens_in", "tokens_out", "cost_usd",
    )
    fieldsets = (
        ("Contexte", {"fields": ("user", "portfolio", "trade_idea", "symbol")}),
        ("Provider", {"fields": ("provider", "model_name", "fallback_used", "fallback_reason")}),
        ("Décision", {"fields": ("decision", "confidence", "expected_rr", "rationale", "risks")}),
        ("Suggestions", {"fields": ("suggested_stake", "suggested_stop_loss", "suggested_take_profit")}),
        ("Audit technique", {
            "classes": ("collapse",),
            "fields": ("prompt_inputs", "raw_response", "latency_ms", "tokens_in", "tokens_out", "cost_usd", "error_message"),
        }),
    )
