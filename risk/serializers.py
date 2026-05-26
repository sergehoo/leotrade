from rest_framework import serializers
from .models import RiskProfile, RiskDecision


class RiskProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskProfile
        fields = "__all__"


class RiskDecisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskDecision
        fields = "__all__"