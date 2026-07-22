from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import Signal, Strategy, StrategyDeployment


@admin.register(Strategy)
class StrategyAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "strategy_type", "asset", "timeframe", "is_active")
    list_filter = ("strategy_type", "is_active", "timeframe", "owner")
    search_fields = ("name", "slug", "asset__symbol", "owner__username", "owner__email")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Signal)
class SignalAdmin(admin.ModelAdmin):
    list_display = ("strategy", "user", "side", "confidence", "price", "status", "candle_time")
    list_filter = ("side", "status", "strategy", "user")
    search_fields = ("strategy__name", "strategy__asset__symbol", "user__username", "user__email")
    date_hierarchy = "candle_time"


@admin.register(StrategyDeployment)
class StrategyDeploymentAdmin(admin.ModelAdmin):
    list_display = (
        "strategy",
        "user",
        "portfolio",
        "broker_account",
        "execution_mode",
        "status",
        "auto_execute",
        "activated_at",
    )
    list_filter = ("execution_mode", "status", "auto_execute")
    search_fields = (
        "strategy__name",
        "user__username",
        "user__email",
        "portfolio__name",
        "broker_account__name",
    )
    readonly_fields = ("activated_at", "paused_at", "created_at", "updated_at")
