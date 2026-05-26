from decimal import Decimal
from rest_framework import serializers


class DepositWithdrawSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    description = serializers.CharField(required=False, allow_blank=True)
    metadata = serializers.JSONField(required=False)

    def validate_amount(self, value):
        if Decimal(str(value)) <= 0:
            raise serializers.ValidationError("Le montant doit être strictement positif.")
        return value


class OrderCreateSerializer(serializers.Serializer):
    portfolio_id = serializers.IntegerField()
    broker_account_id = serializers.IntegerField()
    asset_id = serializers.IntegerField(required=False)
    symbol = serializers.CharField(max_length=50)
    asset_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    side = serializers.ChoiceField(choices=["BUY", "SELL"])
    order_type = serializers.ChoiceField(choices=["MARKET", "LIMIT", "STOP", "STOP_LIMIT"], default="MARKET")
    approved_quantity = serializers.DecimalField(max_digits=24, decimal_places=8)
    requested_stake_amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    approved_notional = serializers.DecimalField(max_digits=18, decimal_places=2)
    requested_price = serializers.DecimalField(max_digits=24, decimal_places=8)
    limit_price = serializers.DecimalField(max_digits=24, decimal_places=8, required=False)
    stop_price = serializers.DecimalField(max_digits=24, decimal_places=8, required=False)
    stop_loss = serializers.DecimalField(max_digits=24, decimal_places=8, required=False)
    take_profit = serializers.DecimalField(max_digits=24, decimal_places=8, required=False)
    leverage = serializers.DecimalField(max_digits=12, decimal_places=4, required=False, default=1)
    signal_id = serializers.IntegerField(required=False)
    trade_idea_id = serializers.IntegerField(required=False)
    source = serializers.ChoiceField(choices=["MANUAL", "AI_ASSISTED", "STRATEGY", "IMPORT"], default="MANUAL")
    metadata = serializers.JSONField(required=False)


class CorrelationComputeSerializer(serializers.Serializer):
    timeframe_code = serializers.CharField(default="1d")
    lookback_bars = serializers.IntegerField(default=90, min_value=5, max_value=1000)