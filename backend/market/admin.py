from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import Asset, Timeframe, Candle, MarketFeature


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ("symbol", "asset_class", "exchange", "is_active")
    list_filter = ("asset_class", "exchange", "is_active")
    search_fields = ("symbol", "base_asset", "quote_asset")


@admin.register(Timeframe)
class TimeframeAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "minutes")
    search_fields = ("code", "label")


@admin.register(Candle)
class CandleAdmin(admin.ModelAdmin):
    list_display = ("asset", "timeframe", "open_time", "close")
    list_filter = ("timeframe", "asset")
    search_fields = ("asset__symbol",)
    date_hierarchy = "open_time"


@admin.register(MarketFeature)
class MarketFeatureAdmin(admin.ModelAdmin):
    list_display = ("asset", "timeframe", "candle_time", "rsi_14", "sma_20", "sma_50")
    list_filter = ("timeframe", "asset")
    search_fields = ("asset__symbol",)