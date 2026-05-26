from rest_framework import serializers

from portfolio.models import (
    Portfolio,
    Position,
    PortfolioSnapshot,
    CashLedgerEntry,
    PortfolioAllocation,
    PositionCorrelation,
)


class PortfolioSerializer(serializers.ModelSerializer):
    broker_name = serializers.CharField(source="broker_account.name", read_only=True)
    broker_type = serializers.CharField(source="broker_account.broker", read_only=True)

    class Meta:
        model = Portfolio
        fields = [
            "id",
            "name",
            "description",
            "base_currency",
            "starting_balance",
            "current_balance",
            "available_cash",
            "locked_cash",
            "equity",
            "unrealized_pnl",
            "realized_pnl",
            "margin_used",
            "max_equity",
            "current_drawdown_percent",
            "max_drawdown_percent",
            "is_active",
            "is_default",
            "last_reconciled_at",
            "notes",
            "broker_account",
            "broker_name",
            "broker_type",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "current_balance",
            "available_cash",
            "locked_cash",
            "equity",
            "unrealized_pnl",
            "realized_pnl",
            "margin_used",
            "max_equity",
            "current_drawdown_percent",
            "max_drawdown_percent",
            "last_reconciled_at",
            "created_at",
            "updated_at",
        ]

    def validate_broker_account(self, value):
        request = self.context.get("request")
        if request and value.user_id != request.user.id:
            raise serializers.ValidationError("Ce broker n'appartient pas à l'utilisateur connecté.")
        return value


class PositionSerializer(serializers.ModelSerializer):
    portfolio_name = serializers.CharField(source="portfolio.name", read_only=True)
    broker_name = serializers.CharField(source="broker_account.name", read_only=True)
    asset_symbol = serializers.CharField(source="asset.symbol", read_only=True)

    class Meta:
        model = Position
        fields = [
            "id",
            "portfolio",
            "portfolio_name",
            "broker_account",
            "broker_name",
            "asset",
            "asset_symbol",
            "symbol",
            "asset_name",
            "side",
            "quantity",
            "entry_price",
            "average_entry_price",
            "current_price",
            "stop_loss",
            "take_profit",
            "leverage",
            "margin_used",
            "notional_value",
            "exposure_value",
            "status",
            "source",
            "cost_basis_status",
            "pnl",
            "pnl_percent",
            "realized_pnl",
            "unrealized_pnl",
            "broker_position_id",
            "broker_order_id",
            "opened_at",
            "closed_at",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "broker_account",
            "notional_value",
            "exposure_value",
            "pnl",
            "pnl_percent",
            "realized_pnl",
            "unrealized_pnl",
            "created_at",
            "updated_at",
        ]

    def validate_portfolio(self, value):
        request = self.context.get("request")
        if request and value.user_id != request.user.id:
            raise serializers.ValidationError("Ce portefeuille n'appartient pas à l'utilisateur connecté.")
        return value

    def create(self, validated_data):
        portfolio = validated_data["portfolio"]
        validated_data["broker_account"] = portfolio.broker_account
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data["broker_account"] = instance.portfolio.broker_account
        return super().update(instance, validated_data)


class PortfolioSnapshotSerializer(serializers.ModelSerializer):
    portfolio_name = serializers.CharField(source="portfolio.name", read_only=True)

    class Meta:
        model = PortfolioSnapshot
        fields = [
            "id",
            "portfolio",
            "portfolio_name",
            "snapshot_time",
            "balance",
            "available_cash",
            "locked_cash",
            "equity",
            "unrealized_pnl",
            "realized_pnl",
            "margin_used",
            "drawdown_percent",
            "daily_return_percent",
            "monthly_return_percent",
            "created_at",
            "updated_at",
        ]


class CashLedgerEntrySerializer(serializers.ModelSerializer):
    portfolio_name = serializers.CharField(source="portfolio.name", read_only=True)

    class Meta:
        model = CashLedgerEntry
        fields = [
            "id",
            "portfolio",
            "portfolio_name",
            "entry_type",
            "amount",
            "currency",
            "reference_type",
            "reference_id",
            "description",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class PortfolioAllocationSerializer(serializers.ModelSerializer):
    asset_symbol = serializers.CharField(source="asset.symbol", read_only=True)

    class Meta:
        model = PortfolioAllocation
        fields = [
            "id",
            "portfolio",
            "asset",
            "asset_symbol",
            "target_weight",
            "max_weight",
            "is_active",
            "created_at",
            "updated_at",
        ]


class PositionCorrelationSerializer(serializers.ModelSerializer):
    asset_a_symbol = serializers.CharField(source="asset_a.symbol", read_only=True)
    asset_b_symbol = serializers.CharField(source="asset_b.symbol", read_only=True)

    class Meta:
        model = PositionCorrelation
        fields = [
            "id",
            "portfolio",
            "asset_a",
            "asset_a_symbol",
            "asset_b",
            "asset_b_symbol",
            "timeframe_code",
            "lookback_bars",
            "correlation_value",
            "created_at",
            "updated_at",
        ]