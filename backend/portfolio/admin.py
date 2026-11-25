from django.contrib import admin
from .models import Portfolio, Position, PortfolioSnapshot, PortfolioAllocation, PositionCorrelation


@admin.register(Portfolio)
class PortfolioAdmin(admin.ModelAdmin):
    list_display = (
        "name", "user", "broker_account", "base_currency",
        "current_balance", "equity", "is_active", "is_default"
    )
    list_filter = ("is_active", "is_default", "base_currency", "broker_account__broker")
    search_fields = ("name", "user__email", "broker_account__name")


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = (
        "portfolio", "asset", "side", "status", "quantity",
        "entry_price", "current_price", "pnl", "opened_at"
    )
    list_filter = ("status", "side", "asset__asset_class")
    search_fields = ("portfolio__name", "asset__symbol")


@admin.register(PortfolioSnapshot)
class PortfolioSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "portfolio", "snapshot_time", "balance", "equity",
        "unrealized_pnl", "realized_pnl", "drawdown_percent"
    )
    list_filter = ("portfolio",)
    search_fields = ("portfolio__name",)


@admin.register(PortfolioAllocation)
class PortfolioAllocationAdmin(admin.ModelAdmin):
    list_display = ("portfolio", "asset", "target_weight", "max_weight", "is_active")
    list_filter = ("is_active",)
    search_fields = ("portfolio__name", "asset__symbol")


@admin.register(PositionCorrelation)
class PositionCorrelationAdmin(admin.ModelAdmin):
    list_display = ("portfolio", "asset_a", "asset_b", "timeframe_code", "correlation_value")
    list_filter = ("timeframe_code",)
    search_fields = ("portfolio__name", "asset_a__symbol", "asset_b__symbol")