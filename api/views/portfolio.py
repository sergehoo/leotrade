from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from api.permissions import IsOwner
from api.serializers.portfolio import (
    PortfolioSerializer,
    PositionSerializer,
    PortfolioSnapshotSerializer,
    CashLedgerEntrySerializer,
    PortfolioAllocationSerializer,
    PositionCorrelationSerializer,
)
from api.serializers.actions import DepositWithdrawSerializer, CorrelationComputeSerializer

from portfolio.models import (
    Portfolio,
    Position,
    PortfolioSnapshot,
    CashLedgerEntry,
    PortfolioAllocation,
    PositionCorrelation,
)
from portfolio.services import PortfolioService, PortfolioAccountingService
from portfolio.broker_import import BrokerImportService


class PortfolioViewSet(viewsets.ModelViewSet):
    serializer_class = PortfolioSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
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

    @action(detail=True, methods=["post"])
    def set_default(self, request, pk=None):
        portfolio = self.get_object()
        PortfolioService.set_default_portfolio(portfolio)
        return Response({"status": "ok", "message": "Portfolio par défaut mis à jour."})

    @action(detail=True, methods=["post"])
    def import_live(self, request, pk=None):
        portfolio = self.get_object()
        imported = BrokerImportService.import_live_positions(portfolio)
        PortfolioService.create_snapshot(portfolio)
        return Response({
            "status": "ok",
            "imported_count": len(imported),
            "portfolio_id": portfolio.id,
        })

    @action(detail=True, methods=["get"])
    def exposures(self, request, pk=None):
        portfolio = self.get_object()
        data = PortfolioService.asset_class_exposure(portfolio)
        return Response(data)

    @action(detail=True, methods=["post"])
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

    @action(detail=True, methods=["post"])
    def deposit(self, request, pk=None):
        portfolio = self.get_object()
        serializer = DepositWithdrawSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        PortfolioAccountingService.deposit(
            portfolio=portfolio,
            amount=serializer.validated_data["amount"],
            description=serializer.validated_data.get("description", "Dépôt API"),
            metadata=serializer.validated_data.get("metadata"),
        )
        PortfolioService.refresh_portfolio_metrics(portfolio)

        return Response(PortfolioSerializer(portfolio, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        portfolio = self.get_object()
        serializer = DepositWithdrawSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        PortfolioAccountingService.withdraw(
            portfolio=portfolio,
            amount=serializer.validated_data["amount"],
            description=serializer.validated_data.get("description", "Retrait API"),
            metadata=serializer.validated_data.get("metadata"),
        )
        PortfolioService.refresh_portfolio_metrics(portfolio)

        return Response(PortfolioSerializer(portfolio, context={"request": request}).data)


class PositionViewSet(viewsets.ModelViewSet):
    serializer_class = PositionSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        return (
            Position.objects
            .filter(portfolio__user=self.request.user)
            .select_related("portfolio", "broker_account", "asset")
            .order_by("-opened_at")
        )

    def perform_create(self, serializer):
        position = serializer.save()
        position.update_market_metrics()
        position.save()
        PortfolioService.refresh_portfolio_metrics(position.portfolio)

    def perform_update(self, serializer):
        position = serializer.save()
        position.update_market_metrics()
        position.save()
        PortfolioService.refresh_portfolio_metrics(position.portfolio)

    def perform_destroy(self, instance):
        portfolio = instance.portfolio
        instance.delete()
        PortfolioService.refresh_portfolio_metrics(portfolio)


class PortfolioSnapshotViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PortfolioSnapshotSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
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
        return (
            PortfolioAllocation.objects
            .filter(portfolio__user=self.request.user)
            .select_related("portfolio", "asset")
        )


class PositionCorrelationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PositionCorrelationSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        return (
            PositionCorrelation.objects
            .filter(portfolio__user=self.request.user)
            .select_related("portfolio", "asset_a", "asset_b")
            .order_by("-created_at")
        )