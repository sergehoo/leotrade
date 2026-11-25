from rest_framework import serializers
from risk.models import RiskProfile, DailyRiskState, WeeklyRiskState, RiskDecision, KillSwitchEvent


class RiskProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskProfile
        fields = [
            "id",
            "user",
            "portfolio",
            "name",
            "is_active",
            "is_default",
            "max_risk_per_trade",
            "max_daily_loss",
            "max_weekly_loss",
            "max_drawdown",
            "max_open_positions",
            "max_symbol_exposure_percent",
            "max_asset_class_exposure_percent",
            "max_correlated_exposure_percent",
            "max_leverage",
            "min_confidence",
            "allow_short",
            "allow_live_trading",
            "require_stop_loss",
            "block_on_high_correlation",
            "kill_switch_enabled",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["user", "created_at", "updated_at"]


class DailyRiskStateSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyRiskState
        fields = "__all__"


class WeeklyRiskStateSerializer(serializers.ModelSerializer):
    class Meta:
        model = WeeklyRiskState
        fields = "__all__"


class RiskDecisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskDecision
        fields = "__all__"


class KillSwitchEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = KillSwitchEvent
        fields = "__all__"