from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from django.db import IntegrityError, transaction


@pytest.mark.django_db
def test_deriv_positions_use_canonical_dto_fields(broker_live):
    from infrastructure.broker_clients.deriv_client import DerivBrokerClient

    broker_live.set_secret("DERIV_TOKEN", "test-token")
    client = DerivBrokerClient(broker_live)
    ws = mock.Mock()
    ws.portfolio_ws.return_value = {
        "portfolio": {
            "contracts": [
                {
                    "contract_id": 123,
                    "contract_type": "CALL",
                    "symbol": "R_100",
                    "buy_price": "10.50",
                    "current_spot": "11.25",
                }
            ]
        }
    }

    with mock.patch.object(client, "_open_authenticated_ws", return_value=ws):
        positions = client.fetch_positions()

    assert len(positions) == 1
    position = positions[0]
    assert position.entry_price == Decimal("10.50")
    assert position.average_entry_price == Decimal("10.50")
    assert position.current_price == Decimal("11.25")
    assert position.broker_position_id == "123"
    ws.close.assert_called_once()


@pytest.mark.django_db
def test_live_adapter_routes_through_broker_gateway(broker_live, portfolio_live):
    from execution.adapters.live_deriv import LiveDerivAdapter
    from infrastructure.broker_clients.gateway import BrokerGateway

    broker_client = mock.Mock()
    with mock.patch(
        "infrastructure.broker_clients.gateway.BrokerClientFactory.build",
        return_value=broker_client,
    ):
        adapter = LiveDerivAdapter(broker_live, portfolio_live)
        order = object()
        adapter.submit_order(order)

    assert isinstance(adapter.client, BrokerGateway)
    broker_client.submit_order.assert_called_once_with(order)


def test_binance_mutation_is_attempted_once():
    from infrastructure.broker_clients.binance_client import BinanceBrokerClient

    client = object.__new__(BinanceBrokerClient)
    client.client = mock.Mock()
    client.client.create_order.side_effect = ConnectionError("response lost")
    client._fetch_local_constraint = mock.Mock(return_value=None)
    order = SimpleNamespace(
        approved_quantity=Decimal("0.1"),
        limit_price=None,
        requested_price=Decimal("100"),
        symbol="BTCUSDT",
        side="BUY",
        order_type="MARKET",
        idempotency_key="stable-key",
        portfolio=SimpleNamespace(base_currency="USDT"),
    )

    with pytest.raises(ConnectionError):
        client.submit_order(order)

    client.client.create_order.assert_called_once()


def test_multifactor_scoring_is_side_aware():
    from trading.services.opportunity_scoring import OpportunityScoringService

    bullish = {
        "close": 110,
        "sma_20": 105,
        "sma_50": 100,
        "ema_20": 106,
        "ema_50": 101,
        "rsi_14": 62,
        "macd": 2,
        "macd_signal": 1,
        "macd_hist": 1,
        "returns_5": 0.03,
        "atr_14": 1.5,
        "volatility_20": 0.01,
        "bb_width": 0.04,
        "bb_pos": 0.7,
        "volume_ratio": 1.4,
    }
    bearish = {
        **bullish,
        "close": 90,
        "sma_20": 95,
        "sma_50": 100,
        "ema_20": 94,
        "ema_50": 99,
        "rsi_14": 38,
        "macd": -2,
        "macd_signal": -1,
        "macd_hist": -1,
        "returns_5": -0.03,
        "bb_pos": 0.3,
    }

    buy_score = OpportunityScoringService.score(bullish)
    sell_score = OpportunityScoringService.score(bearish)

    assert buy_score["direction"] == "BUY"
    assert sell_score["direction"] == "SELL"
    assert buy_score["regime"] == "TREND_UP"
    assert sell_score["regime"] == "TREND_DOWN"
    assert 0 <= buy_score["confidence_score"] <= 1
    assert 0 <= sell_score["confidence_score"] <= 1


@pytest.mark.django_db
def test_market_scan_creates_one_run_without_assets():
    from trading.models import MarketScanRun
    from trading.services.market_scanner import MarketScannerService

    run, rows = MarketScannerService.scan(timeframe_code="5m")

    assert rows == []
    assert MarketScanRun.objects.filter(pk=run.pk).count() == 1
    assert MarketScanRun.objects.count() == 1


@pytest.mark.django_db
def test_broker_fill_identifier_is_unique_per_order(
    user,
    broker_paper,
    portfolio_paper,
):
    from execution.models import ExecutionFill, Order

    order = Order.objects.create(
        user=user,
        portfolio=portfolio_paper,
        broker_account=broker_paper,
        symbol="R_100",
        side="BUY",
        approved_quantity=Decimal("1"),
        approved_notional=Decimal("10"),
        idempotency_key="fill-unique-test",
    )
    payload = {
        "order": order,
        "broker_fill_id": "broker-fill-1",
        "quantity": Decimal("1"),
        "price": Decimal("10"),
        "notional": Decimal("10"),
    }
    ExecutionFill.objects.create(**payload)

    with pytest.raises(IntegrityError), transaction.atomic():
        ExecutionFill.objects.create(**payload)


def test_submitting_is_a_declared_order_status():
    from execution.models import Order

    statuses = dict(Order.STATUS_CHOICES)
    assert statuses["SUBMITTING"] == "Submitting"
    assert statuses["UNKNOWN_BROKER_STATE"] == "Unknown Broker State"


def test_production_settings_use_boolean_env_helper():
    source = Path("leoTrade/settings/prod.py").read_text(encoding="utf-8")
    assert 'env("FEATURE_TRADING_ENABLED", False, bool)' in source
    assert "env.bool(" not in source
    assert "len(SECRET_KEY) < 50" in source


def test_paper_order_without_reference_price_is_rejected():
    from execution.adapters.paper import PaperBrokerAdapter

    adapter = PaperBrokerAdapter(
        broker_account=object(),
        portfolio=SimpleNamespace(base_currency="USD"),
    )
    order = SimpleNamespace(
        requested_price=Decimal("0"),
        limit_price=None,
        approved_quantity=Decimal("1"),
    )

    with pytest.raises(ValueError, match="positive reference price"):
        adapter.submit_order(order)


@pytest.mark.django_db
def test_gateway_does_not_retry_validation_errors(broker_paper):
    from infrastructure.broker_clients.gateway import BrokerGateway

    broker_client = mock.Mock()
    broker_client.fetch_balances.side_effect = ValueError("invalid account")
    gateway = BrokerGateway(broker_paper, client=broker_client)

    with pytest.raises(ValueError, match="invalid account"):
        gateway.fetch_balances()

    broker_client.fetch_balances.assert_called_once()


def test_legacy_orchestrator_is_the_canonical_service():
    from execution.orchestrator import ExecutionOrchestrator as LegacyImport
    from execution.services import ExecutionOrchestrator as CanonicalImport

    assert LegacyImport is CanonicalImport


@pytest.mark.django_db
def test_transient_submit_error_keeps_cash_locked_for_reconciliation(
    user,
    broker_paper,
    portfolio_paper,
):
    from execution.models import Order
    from execution.services import ExecutionOrchestrator

    order = Order.objects.create(
        user=user,
        portfolio=portfolio_paper,
        broker_account=broker_paper,
        symbol="R_100",
        side="BUY",
        approved_quantity=Decimal("1"),
        approved_notional=Decimal("10"),
        requested_stake_amount=Decimal("10"),
        requested_price=Decimal("10"),
        idempotency_key="ambiguous-submit",
    )
    adapter = mock.Mock()
    adapter.submit_order.side_effect = ConnectionError("response lost")

    with mock.patch.object(
        ExecutionOrchestrator,
        "validate_order_risk",
    ), mock.patch(
        "execution.services.PortfolioAccountingService.lock_cash_for_order",
    ), mock.patch(
        "execution.services.PortfolioAccountingService.release_cash_from_order",
    ) as release_cash, mock.patch(
        "execution.services.BrokerAdapterFactory.build",
        return_value=adapter,
    ), mock.patch("core.outbox._nudge_publisher"):
        with pytest.raises(ConnectionError):
            ExecutionOrchestrator.submit_order(order)

    order.refresh_from_db()
    assert order.status == "UNKNOWN_BROKER_STATE"
    assert order.is_open is True
    assert order.metadata["broker_state_unknown"] is True
    release_cash.assert_not_called()


@pytest.mark.django_db
def test_async_submit_task_marks_ambiguous_broker_state(
    user,
    broker_paper,
    portfolio_paper,
):
    from execution.models import Order
    from execution.tasks import submit_order_to_broker_task

    order = Order.objects.create(
        user=user,
        portfolio=portfolio_paper,
        broker_account=broker_paper,
        symbol="R_100",
        side="BUY",
        approved_quantity=Decimal("1"),
        approved_notional=Decimal("10"),
        requested_price=Decimal("10"),
        idempotency_key="ambiguous-task",
    )
    adapter = mock.Mock()
    adapter.submit_order.side_effect = TimeoutError("broker timeout")

    with mock.patch(
        "execution.adapters.factory.BrokerAdapterFactory.build",
        return_value=adapter,
    ), mock.patch("core.outbox._nudge_publisher"):
        result = submit_order_to_broker_task(order.id)

    from core.models import OutboxEvent
    from execution.event_topics import PORTFOLIO_RECONCILE_REQUESTED

    order.refresh_from_db()
    assert result["unknown_broker_state"] is True
    assert order.status == "UNKNOWN_BROKER_STATE"
    assert OutboxEvent.objects.filter(
        topic=PORTFOLIO_RECONCILE_REQUESTED,
        aggregate_id=str(portfolio_paper.id),
    ).exists()
