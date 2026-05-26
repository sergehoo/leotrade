from django.contrib import admin
from .models_ai import (
    MarketScanRun,
    MarketOpportunity,
    TradeRecommendation,
    AIModelRegistry,
    AIInferenceLog,
    DecisionAudit,
)


@admin.register(MarketScanRun)
class MarketScanRunAdmin(admin.ModelAdmin):
    list_display = ("id", "source", "timeframe_code", "status", "started_at", "finished_at")
    list_filter = ("status", "timeframe_code", "source")
    search_fields = ("source", "universe", "message")


@admin.register(MarketOpportunity)
class MarketOpportunityAdmin(admin.ModelAdmin):
    list_display = (
        "id", "symbol", "direction", "timeframe_code",
        "overall_score", "confidence_score", "status", "expires_at"
    )
    list_filter = ("status", "direction", "timeframe_code", "regime_label")
    search_fields = ("symbol", "asset_name", "explanation")


@admin.register(TradeRecommendation)
class TradeRecommendationAdmin(admin.ModelAdmin):
    list_display = (
        "id", "user", "portfolio", "opportunity",
        "recommendation_type", "status",
        "stake_amount", "recommended_notional",
        "ai_confidence", "expires_at",
    )
    list_filter = ("status", "recommendation_type", "broker_account__broker")
    search_fields = ("user__email", "portfolio__name", "opportunity__symbol")


@admin.register(AIModelRegistry)
class AIModelRegistryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "provider", "model_name", "version", "model_type", "is_active")
    list_filter = ("provider", "model_type", "is_active")
    search_fields = ("name", "model_name", "version")


@admin.register(AIInferenceLog)
class AIInferenceLogAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "portfolio", "model", "latency_ms", "cost_estimate", "success", "created_at")
    list_filter = ("success", "model__provider", "model__model_type")
    search_fields = ("user__email", "portfolio__name", "prompt_hash", "error_message")


@admin.register(DecisionAudit)
class DecisionAuditAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "portfolio", "final_decision", "created_at")
    list_filter = ("final_decision",)
    search_fields = ("user__email", "portfolio__name", "notes")