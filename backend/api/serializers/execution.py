from rest_framework import serializers

from execution.models import Order, ExecutionFill, ExecutionEvent, BrokerSyncLog


class ExecutionFillSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExecutionFill
        fields = [
            "id",
            "broker_fill_id",
            "quantity",
            "price",
            "notional",
            "fee",
            "fee_currency",
            "fill_time",
            "liquidity_type",
            "metadata",
            "created_at",
            "updated_at",
        ]


class ExecutionEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExecutionEvent
        fields = [
            "id",
            "event_type",
            "message",
            "payload",
            "created_by_system",
            "created_at",
            "updated_at",
        ]


class OrderSerializer(serializers.ModelSerializer):
    portfolio_name = serializers.CharField(source="portfolio.name", read_only=True)
    broker_name = serializers.CharField(source="broker_account.name", read_only=True)
    asset_symbol = serializers.CharField(source="asset.symbol", read_only=True)
    fills = ExecutionFillSerializer(many=True, read_only=True)
    events = ExecutionEventSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "portfolio",
            "portfolio_name",
            "broker_account",
            "broker_name",
            "signal",
            "trade_idea",
            "asset",
            "asset_symbol",
            "symbol",
            "asset_name",
            "side",
            "order_type",
            "mode",
            "source",
            "requested_quantity",
            "approved_quantity",
            "filled_quantity",
            "requested_stake_amount",
            "approved_notional",
            "filled_notional",
            "requested_price",
            "limit_price",
            "stop_price",
            "average_fill_price",
            "stop_loss",
            "take_profit",
            "leverage",
            "estimated_fee",
            "actual_fee",
            "status",
            "broker_order_id",
            "broker_client_order_id",
            "submitted_at",
            "filled_at",
            "cancelled_at",
            "rejected_at",
            "expired_at",
            "idempotency_key",
            "execution_notes",
            "metadata",
            "fills",
            "events",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "mode",
            "filled_quantity",
            "filled_notional",
            "average_fill_price",
            "actual_fee",
            "status",
            "broker_order_id",
            "broker_client_order_id",
            "submitted_at",
            "filled_at",
            "cancelled_at",
            "rejected_at",
            "expired_at",
            "idempotency_key",
            "fills",
            "events",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        request = self.context.get("request")
        portfolio = attrs.get("portfolio")
        broker_account = attrs.get("broker_account")

        if request and portfolio and portfolio.user_id != request.user.id:
            raise serializers.ValidationError({"portfolio": "Ce portefeuille ne vous appartient pas."})

        if request and broker_account and broker_account.user_id != request.user.id:
            raise serializers.ValidationError({"broker_account": "Ce broker ne vous appartient pas."})

        if portfolio and broker_account and portfolio.broker_account_id != broker_account.id:
            raise serializers.ValidationError("Le portefeuille n'est pas rattaché à ce broker.")

        return attrs


class BrokerSyncLogSerializer(serializers.ModelSerializer):
    broker_name = serializers.CharField(source="broker_account.name", read_only=True)
    portfolio_name = serializers.CharField(source="portfolio.name", read_only=True)

    class Meta:
        model = BrokerSyncLog
        fields = [
            "id",
            "broker_account",
            "broker_name",
            "portfolio",
            "portfolio_name",
            "sync_type",
            "status",
            "started_at",
            "finished_at",
            "processed_count",
            "error_count",
            "message",
            "payload",
            "created_at",
            "updated_at",
        ]