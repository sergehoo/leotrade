from rest_framework import serializers
from .models import Strategy, Signal


class StrategySerializer(serializers.ModelSerializer):
    class Meta:
        model = Strategy
        fields = "__all__"


class SignalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Signal
        fields = "__all__"