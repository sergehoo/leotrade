from rest_framework import serializers

from api.fields import OwnedRelatedField

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
    # Le mode est porté par le compte broker. L'exposer ici évite au client
    # de devoir recouper deux ressources pour savoir si un portefeuille
    # engage de l'argent réel — recoupement qu'il ferait tôt ou tard de
    # travers.
    trading_mode = serializers.CharField(source="broker_account.mode", read_only=True)
    is_simulated = serializers.SerializerMethodField()

    @staticmethod
    def get_is_simulated(obj) -> bool:
        """Vrai quand aucun ordre de ce portefeuille n'atteint un marché."""
        broker = getattr(obj, "broker_account", None)
        if broker is None:
            return True
        return broker.mode == "PAPER" or broker.broker == "SIMULATION"

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
            "trading_mode",
            "is_simulated",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
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
    # Même faille que sur RiskProfile : sans restriction, une allocation
    # s'écrit sur le portefeuille d'un autre utilisateur.
    portfolio = OwnedRelatedField(queryset=Portfolio.objects.all(), owner_lookup="user")

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


class PaperOnboardingSerializer(serializers.Serializer):
    """Entrée du parcours d'accueil en simulation."""

    name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    starting_balance = serializers.DecimalField(
        max_digits=18, decimal_places=2, required=False,
    )
    currency = serializers.CharField(max_length=10, required=False, default="USD")

    def validate_currency(self, value: str) -> str:
        return (value or "USD").strip().upper()


class PortfolioSummarySerializer(serializers.Serializer):
    """Synthèse consolidée d'un portefeuille.

    Les montants transitent en chaîne : le backend calcule en `Decimal`,
    et ni TypeScript ni Dart n'ont d'équivalent natif. Les reconvertir en
    nombre flottant pour les transporter rouvrirait une classe d'erreurs
    d'arrondi que le backend a précisément éliminée.
    """

    portfolio_id = serializers.IntegerField()
    base_currency = serializers.CharField()
    trading_mode = serializers.CharField()
    is_simulated = serializers.BooleanField()

    equity = serializers.CharField()
    current_balance = serializers.CharField()
    available_cash = serializers.CharField()
    locked_cash = serializers.CharField()
    margin_used = serializers.CharField()

    unrealized_pnl = serializers.CharField()
    realized_pnl = serializers.CharField()
    total_pnl = serializers.CharField()
    total_pnl_percent = serializers.CharField()

    current_drawdown_percent = serializers.FloatField()
    max_drawdown_percent = serializers.FloatField()

    open_positions = serializers.IntegerField()
    long_positions = serializers.IntegerField()
    short_positions = serializers.IntegerField()
    winning_positions = serializers.IntegerField()
    losing_positions = serializers.IntegerField()

    exposure_value = serializers.CharField()
    exposure_percent = serializers.CharField()
    asset_class_exposure = serializers.ListField(child=serializers.DictField())


class EquityPointSerializer(serializers.Serializer):
    at = serializers.DateTimeField()
    equity = serializers.CharField()
    balance = serializers.CharField()
    unrealized_pnl = serializers.CharField()
    realized_pnl = serializers.CharField()
    drawdown_percent = serializers.FloatField()


class EquityCurveSerializer(serializers.Serializer):
    """Série de valorisation, avec de quoi juger s'il y a lieu de la tracer.

    Un graphique affirme plus fort qu'un nombre : relier des points épars
    donne à voir une trajectoire qui n'a jamais été mesurée. Le verdict
    est rendu par le serveur pour que deux clients ne tranchent pas
    différemment.
    """

    portfolio_id = serializers.IntegerField()
    base_currency = serializers.CharField()
    points = EquityPointSerializer(many=True)
    point_count = serializers.IntegerField()
    first_at = serializers.DateTimeField(allow_null=True)
    last_at = serializers.DateTimeField(allow_null=True)
    age_seconds = serializers.IntegerField(allow_null=True)
    #: Écart médian entre deux mesures. Au-delà d'un jour et demi,
    #: l'interpolation invente plus qu'elle ne montre.
    median_gap_seconds = serializers.IntegerField(allow_null=True)
    is_plottable = serializers.BooleanField()
    not_plottable_reasons = serializers.ListField(child=serializers.CharField())
    minimum_points = serializers.IntegerField()
