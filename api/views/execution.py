from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from api.permissions import IsOwner
from api.serializers.execution import (
    OrderSerializer,
    ExecutionFillSerializer,
    ExecutionEventSerializer,
    BrokerSyncLogSerializer,
)
from api.serializers.actions import OrderCreateSerializer

from execution.models import Order, ExecutionFill, ExecutionEvent, BrokerSyncLog
from execution.services import ExecutionOrchestrator
from execution.reconciliation import BrokerReconciliationService

from portfolio.models import Portfolio
from brokers.models import BrokerAccount
from market.models import Asset
from strategies.models import Signal
from trading.models import TradeIdea
from execution.idempotency import IdempotencyService

class OrderViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        return (
            Order.objects
            .filter(user=self.request.user)
            .select_related("portfolio", "broker_account", "asset", "signal", "trade_idea")
            .prefetch_related("fills", "events")
            .order_by("-created_at")
        )

    @action(detail=False, methods=["post"])
    def create_manual(self, request):
        idem_key = request.headers.get("X-Idempotency-Key")
        if not idem_key:
            return Response(
                {"detail": "Header X-Idempotency-Key requis."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        record, created = IdempotencyService.get_or_create_record(
            user=request.user,
            endpoint="orders.create_manual",
            key=idem_key,
            payload=request.data,
        )

        if not created:
            return Response(record.response_payload, status=record.status_code)
        serializer = OrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        portfolio = Portfolio.objects.filter(id=data["portfolio_id"], user=request.user).first()
        if not portfolio:
            return Response({"detail": "Portfolio introuvable."}, status=status.HTTP_404_NOT_FOUND)

        broker_account = BrokerAccount.objects.filter(id=data["broker_account_id"], user=request.user).first()
        if not broker_account:
            return Response({"detail": "Broker introuvable."}, status=status.HTTP_404_NOT_FOUND)

        if portfolio.broker_account_id != broker_account.id:
            return Response(
                {"detail": "Le portefeuille n'est pas rattaché à ce broker."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        asset = None
        if data.get("asset_id"):
            asset = Asset.objects.filter(id=data["asset_id"]).first()

        signal = None
        if data.get("signal_id"):
            signal = Signal.objects.filter(id=data["signal_id"]).first()

        trade_idea = None
        if data.get("trade_idea_id"):
            trade_idea = TradeIdea.objects.filter(id=data["trade_idea_id"], user=request.user).first()

        order = ExecutionOrchestrator.create_order(
            user=request.user,
            portfolio=portfolio,
            broker_account=broker_account,
            symbol=data["symbol"],
            side=data["side"],
            approved_quantity=data["approved_quantity"],
            requested_stake_amount=data["requested_stake_amount"],
            approved_notional=data["approved_notional"],
            requested_price=data["requested_price"],
            signal=signal,
            trade_idea=trade_idea,
            asset=asset,
            order_type=data["order_type"],
            source=data["source"],
            stop_loss=data.get("stop_loss"),
            take_profit=data.get("take_profit"),
            leverage=data.get("leverage", 1),
            metadata=data.get("metadata", {}),
        )

        response_payload = OrderSerializer(order, context={"request": request}).data
        IdempotencyService.save_response(record, status.HTTP_201_CREATED, response_payload)
        return Response(response_payload, status=status.HTTP_201_CREATED)

        return Response(
            OrderSerializer(order, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        order = self.get_object()
        ExecutionOrchestrator.submit_order(order)
        order.refresh_from_db()
        return Response(OrderSerializer(order, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = self.get_object()
        ExecutionOrchestrator.cancel_order(order)
        order.refresh_from_db()
        return Response(OrderSerializer(order, context={"request": request}).data)


class ExecutionFillViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ExecutionFillSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        return (
            ExecutionFill.objects
            .filter(order__user=self.request.user)
            .select_related("order")
            .order_by("-fill_time")
        )


class ExecutionEventViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ExecutionEventSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        return (
            ExecutionEvent.objects
            .filter(order__user=self.request.user)
            .select_related("order")
            .order_by("-created_at")
        )


class BrokerSyncLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = BrokerSyncLogSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        return (
            BrokerSyncLog.objects
            .filter(portfolio__user=self.request.user)
            .select_related("portfolio", "broker_account")
            .order_by("-started_at")
        )

    @action(detail=False, methods=["post"])
    def reconcile_portfolio(self, request):
        portfolio_id = request.data.get("portfolio_id")
        portfolio = Portfolio.objects.filter(id=portfolio_id, user=request.user).first()
        if not portfolio:
            return Response({"detail": "Portfolio introuvable."}, status=status.HTTP_404_NOT_FOUND)

        log = BrokerReconciliationService.reconcile_orders(portfolio)
        return Response(BrokerSyncLogSerializer(log, context={"request": request}).data)