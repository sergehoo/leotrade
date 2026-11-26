from rest_framework import serializers

from api.fields import OwnedRelatedField
from portfolio.models import Portfolio
from risk.models import RiskProfile, DailyRiskState, WeeklyRiskState, RiskDecision, KillSwitchEvent


class RiskProfileSerializer(serializers.ModelSerializer):
    # Sans cette restriction, un compte tiers crée un profil sur le
    # portefeuille d'autrui : `perform_create` fixe le `user`, mais la clé
    # du portefeuille vient du corps de la requête. Le profil injecté
    # arrivant avec `is_default=True`, il devient celui que le moteur de
    # risque applique.
    portfolio = OwnedRelatedField(queryset=Portfolio.objects.all(), owner_lookup="user")

    portfolio_name = serializers.CharField(source="portfolio.name", read_only=True)

    class Meta:
        model = RiskProfile
        fields = [
            "id",
            "user",
            "portfolio",
            "portfolio_name",
            "name",
            "is_active",
            "is_default",
            "max_risk_per_trade",
            "max_daily_loss",
            "max_weekly_loss",
            "max_monthly_loss",
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
            # Capital Preservation First — ces trois drapeaux pilotent
            # l'univers d'instruments autorisé. Absents du contrat jusqu'ici,
            # ils rendaient la politique invisible et non modifiable depuis
            # les clients, alors qu'elle est la principale protection du
            # capital.
            "preservation_mode",
            "allow_volatile_instruments",
            "allow_speculative_instruments",
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