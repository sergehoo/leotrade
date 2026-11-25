from rest_framework import serializers
from trading.models_ai import (
    MarketScanRun,
    MarketOpportunity,
    TradeRecommendation,
    AIModelRegistry,
    AIInferenceLog,
    DecisionAudit,
)


class MarketScanRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketScanRun
        fields = "__all__"


class MarketOpportunitySerializer(serializers.ModelSerializer):
    asset_symbol = serializers.CharField(source="asset.symbol", read_only=True)

    class Meta:
        model = MarketOpportunity
        fields = "__all__"


class TradeRecommendationSerializer(serializers.ModelSerializer):
    symbol = serializers.CharField(source="opportunity.symbol", read_only=True)
    direction = serializers.CharField(source="opportunity.direction", read_only=True)

    class Meta:
        model = TradeRecommendation
        fields = "__all__"


class AIModelRegistrySerializer(serializers.ModelSerializer):
    class Meta:
        model = AIModelRegistry
        fields = "__all__"


class AIInferenceLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIInferenceLog
        fields = "__all__"


class DecisionAuditSerializer(serializers.ModelSerializer):
    class Meta:
        model = DecisionAudit
        fields = "__all__"