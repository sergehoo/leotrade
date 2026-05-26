from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import Strategy, Signal


@admin.register(Strategy)
class StrategyAdmin(admin.ModelAdmin):
    list_display = ("name", "strategy_type", "asset", "timeframe", "is_active")
    list_filter = ("strategy_type", "is_active", "timeframe")
    search_fields = ("name", "slug", "asset__symbol")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Signal)
class SignalAdmin(admin.ModelAdmin):
    list_display = ("strategy", "side", "confidence", "price", "status", "candle_time")
    list_filter = ("side", "status", "strategy")
    search_fields = ("strategy__name", "strategy__asset__symbol")
    date_hierarchy = "candle_time"