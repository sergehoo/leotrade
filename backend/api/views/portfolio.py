from drf_spectacular.utils import extend_schema
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from api.permissions import IsOwner
from api.serializers.portfolio import (
    EquityCurveSerializer,
    PaperOnboardingSerializer,
    PortfolioSummarySerializer,
    PortfolioSerializer,
    PositionSerializer,
    PortfolioSnapshotSerializer,
    CashLedgerEntrySerializer,
    PortfolioAllocationSerializer,
    PositionCorrelationSerializer,
)
from api.serializers.actions import CorrelationComputeSerializer

from portfolio.models import (
    Portfolio,
    Position,
    PortfolioSnapshot,
    CashLedgerEntry,
    PortfolioAllocation,
    PositionCorrelation,
)
from portfolio.services import PortfolioService
from portfolio.services_onboarding import OnboardingError, PaperOnboardingService
from portfolio.services_equity_curve import EquityCurveService
from portfolio.services_summary import PortfolioSummaryService
from portfolio.broker_import import BrokerImportService


class PortfolioViewSet(viewsets.ModelViewSet):
    serializer_class = PortfolioSerializer
    permission_classes = [IsOwner]
    filterset_fields = ["is_active", "is_default", "base_currency"]
    search_fields = ["name", "description"]
    ordering_fields = ["name", "equity", "created_at"]
    ordering = ["-is_default", "name"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Portfolio.objects.none()
        return (
            Portfolio.objects
            .filter(user=self.request.user)
            .select_related("broker_account")
            .order_by("name")
        )

    def perform_create(self, serializer):
        portfolio = serializer.save(user=self.request.user)
        PortfolioService.refresh_portfolio_metrics(portfolio)

    def perform_update(self, serializer):
        portfolio = serializer.save()
        PortfolioService.refresh_portfolio_metrics(portfolio)

    @action(detail=True, methods=["post"])
    def refresh(self, request, pk=None):
        portfolio = self.get_object()
        PortfolioService.refresh_portfolio_metrics(portfolio)
        return Response(PortfolioSerializer(portfolio, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def snapshot(self, request, pk=None):
        portfolio = self.get_object()
        snapshot = PortfolioService.create_snapshot(portfolio)
        return Response(
            PortfolioSnapshotSerializer(snapshot, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="set-default")
    def set_default(self, request, pk=None):
        portfolio = self.get_object()
        PortfolioService.set_default_portfolio(portfolio)
        return Response({"status": "ok", "message": "Portfolio par défaut mis à jour."})

    @action(detail=True, methods=["post"], url_path="import-live")
    def import_live(self, request, pk=None):
        portfolio = self.get_object()
        broker = portfolio.broker_account
        if broker.mode != "LIVE" or not broker.is_active or broker.status != "ACTIVE":
            return Response(
                {
                    "detail": (
                        "L'import distant exige un compte broker LIVE actif "
                        "et validé."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )
        imported = BrokerImportService.import_live_positions(portfolio)
        PortfolioService.create_snapshot(portfolio)
        return Response({
            "status": "ok",
            "imported_count": len(imported),
            "portfolio_id": portfolio.id,
        })

    @extend_schema(
        request=PaperOnboardingSerializer,
        responses={201: PortfolioSerializer},
        summary="Créer un portefeuille de simulation prêt à l'emploi",
        description=(
            "Provisionne en un appel une place d'exécution locale, un "
            "portefeuille et son capital de départ. Aucun compte broker "
            "réel n'est requis : c'est le point d'entrée de la plateforme."
        ),
    )
    @action(detail=False, methods=["post"], url_path="provision-paper")
    def provision_paper(self, request):
        payload = PaperOnboardingSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data

        try:
            portfolio = PaperOnboardingService.provision(
                request.user,
                name=(data.get("name") or "").strip() or None,
                starting_balance=data.get("starting_balance"),
                currency=data.get("currency") or "USD",
            )
        except OnboardingError as exc:
            return Response(
                {"code": exc.code, "detail": exc.message},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            PortfolioSerializer(portfolio, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        responses={200: PortfolioSummarySerializer},
        summary="Synthèse consolidée : P&L, exposition, positions",
    )
    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        portfolio = self.get_object()
        return Response(PortfolioSummaryService.build(portfolio))

    @extend_schema(
        responses={200: EquityCurveSerializer},
        summary="Série de valorisation, avec le verdict de traçabilité",
        description=(
            "Renvoie les instantanés ET de quoi juger s'il y a lieu de les "
            "tracer : nombre de points, écart médian, `is_plottable`. Relier "
            "des points épars donne à voir une trajectoire qui n'a jamais "
            "été mesurée."
        ),
    )
    @action(detail=True, methods=["get"], url_path="equity-curve")
    def equity_curve(self, request, pk=None):
        portfolio = self.get_object()
        curve = EquityCurveService.build(
            portfolio, limit=request.query_params.get("limit") or 365,
        )
        return Response(EquityCurveSerializer(curve).data)

    @action(detail=True, methods=["get"])
    def exposures(self, request, pk=None):
        portfolio = self.get_object()
        data = PortfolioService.asset_class_exposure(portfolio)
        return Response(data)

    @action(detail=True, methods=["post"], url_path="compute-correlations")
    def compute_correlations(self, request, pk=None):
        portfolio = self.get_object()
        serializer = CorrelationComputeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        rows = PortfolioService.position_correlation_matrix(
            portfolio,
            timeframe_code=serializer.validated_data["timeframe_code"],
            lookback_bars=serializer.validated_data["lookback_bars"],
        )
        return Response(
            PositionCorrelationSerializer(rows, many=True, context={"request": request}).data
        )

class PositionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PositionSerializer
    permission_classes = [IsOwner]
    filterset_fields = ["status", "side", "symbol", "portfolio", "source"]
    search_fields = ["symbol", "asset_name"]
    ordering_fields = ["opened_at", "symbol", "unrealized_pnl", "exposure_value"]
    ordering = ["-opened_at"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Position.objects.none()

        queryset = (
            Position.objects
            .filter(portfolio__user=self.request.user)
            .select_related("portfolio", "broker_account", "asset")
            .order_by("-opened_at")
        )

        # Séparation stricte simulation / réel : sans ce filtre, un écran
        # unique mélangerait des positions simulées et des positions qui
        # engagent de l'argent réel, dans le même tableau.
        mode = (self.request.query_params.get("trading_mode") or "").upper()
        if mode in {"PAPER", "LIVE"}:
            queryset = queryset.filter(broker_account__mode=mode)
        return queryset

class PortfolioSnapshotViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PortfolioSnapshotSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return PortfolioSnapshot.objects.none()
        return (
            PortfolioSnapshot.objects
            .filter(portfolio__user=self.request.user)
            .select_related("portfolio")
            .order_by("-snapshot_time")
        )


class CashLedgerEntryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CashLedgerEntrySerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return CashLedgerEntry.objects.none()
        return (
            CashLedgerEntry.objects
            .filter(portfolio__user=self.request.user)
            .select_related("portfolio")
            .order_by("-created_at")
        )


class PortfolioAllocationViewSet(viewsets.ModelViewSet):
    serializer_class = PortfolioAllocationSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return PortfolioAllocation.objects.none()
        return (
            PortfolioAllocation.objects
            .filter(portfolio__user=self.request.user)
            .select_related("portfolio", "asset")
        )


class PositionCorrelationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PositionCorrelationSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return PositionCorrelation.objects.none()
        return (
            PositionCorrelation.objects
            .filter(portfolio__user=self.request.user)
            .select_related("portfolio", "asset_a", "asset_b")
            .order_by("-created_at")
        )
