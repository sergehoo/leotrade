from rest_framework import serializers
from .models import Asset, Timeframe, Candle, MarketFeature


class AssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Asset
        fields = "__all__"


class TimeframeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Timeframe
        fields = "__all__"


class CandleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Candle
        fields = "__all__"


class MarketFeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketFeature
        fields = "__all__"