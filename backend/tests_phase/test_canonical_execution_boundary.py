from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from django.utils import timezone


pytestmark = pytest.mark.django_db
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def paper_signal(user):
    from market.models import Asset, Timeframe
    from strategies.models import Signal, Strategy

    asset = Asset.objects.create(
        name="Canonical Asset",
        symbol="CANONUSD",
        asset_class="CRYPTO",
        exchange="TEST",
    )
    timeframe = Timeframe.objects.create(
        code="canonical-5m",
        label="Canonical 5 minutes",
        minutes=5,
    )
    strategy = Strategy.objects.create(
        owner=user,
        name="Canonical Strategy",
        asset=asset,
        timeframe=timeframe,
        status="PAPER",
        is_active=True,
    )
    return Signal.objects.create(
        strategy=strategy,
        user=user,
        candle_time=timezone.now(),
        side="BUY",
        confidence=0.95,
        price=Decimal("100"),
        status="APPROVED",
    )


def test_legacy_execution_facade_writes_only_canonical_order(
    broker_paper,
    portfolio_paper,
    risk_profile_paper,
    paper_signal,
):
    from execution.models import Order as ExecutionOrder
    from trading.models import Order as LegacyOrder
    from trading.services.execution.base_execution import ExecutionService

    order = ExecutionService(broker_paper, portfolio_paper).execute_signal(
        paper_signal,
        Decimal("25"),
    )

    assert isinstance(order, ExecutionOrder)
    assert order.status == "FILLED"
    assert order.approved_quantity == Decimal("1")
    assert order.approved_notional == Decimal("25")
    assert LegacyOrder.objects.count() == 0
    assert portfolio_paper.positions.filter(
        metadata__origin_order_id=order.id,
        status="OPEN",
    ).exists()


def test_signal_execution_is_idempotent(
    broker_paper,
    portfolio_paper,
    risk_profile_paper,
    paper_signal,
):
    from execution.models import Order
    from trading.services.execution.base_execution import ExecutionService

    service = ExecutionService(broker_paper, portfolio_paper)
    first = service.execute_signal(paper_signal, Decimal("25"))
    second = service.execute_signal(paper_signal, Decimal("25"))

    assert first.id == second.id
    assert Order.objects.filter(signal=paper_signal).count() == 1


def test_direct_submit_honours_global_kill_switch(
    settings,
    user,
    broker_paper,
    portfolio_paper,
):
    from execution.exceptions import TradingDisabled
    from execution.services import ExecutionOrchestrator

    order = ExecutionOrchestrator.create_order(
        user=user,
        portfolio=portfolio_paper,
        broker_account=broker_paper,
        symbol="CANONUSD",
        side="BUY",
        approved_quantity=Decimal("1"),
        requested_stake_amount=Decimal("100"),
        approved_notional=Decimal("100"),
        requested_price=Decimal("100"),
    )
    settings.FEATURE_TRADING_ENABLED = False

    with mock.patch("execution.services.BrokerAdapterFactory.build") as build:
        with pytest.raises(TradingDisabled):
            ExecutionOrchestrator.submit_order(order)

    build.assert_not_called()
    order.refresh_from_db()
    assert order.status == "PENDING_SUBMIT"


def test_async_submit_honours_last_mile_kill_switch(
    settings,
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
        symbol="CANONUSD",
        side="BUY",
        mode="PAPER",
        status="PENDING_SUBMIT",
        requested_quantity=Decimal("1"),
        approved_quantity=Decimal("1"),
        requested_stake_amount=Decimal("100"),
        approved_notional=Decimal("100"),
        requested_price=Decimal("100"),
        idempotency_key="async-kill-switch",
    )
    settings.FEATURE_TRADING_ENABLED = False

    with mock.patch("execution.adapters.factory.BrokerAdapterFactory.build") as build:
        result = submit_order_to_broker_task.run(order.id)

    build.assert_not_called()
    order.refresh_from_db()
    assert result == {"ok": False, "err": "trading_disabled"}
    assert order.status == "REJECTED"


def test_direct_submit_honours_portfolio_kill_switch(
    user,
    broker_paper,
    portfolio_paper,
):
    from execution.exceptions import OrderRejected
    from execution.services import ExecutionOrchestrator

    order = ExecutionOrchestrator.create_order(
        user=user,
        portfolio=portfolio_paper,
        broker_account=broker_paper,
        symbol="CANONUSD",
        side="BUY",
        approved_quantity=Decimal("1"),
        requested_stake_amount=Decimal("100"),
        approved_notional=Decimal("100"),
        requested_price=Decimal("100"),
    )

    with mock.patch(
        "execution.services.RiskGuardService.has_active_kill_switch",
        return_value=True,
    ), mock.patch("execution.services.BrokerAdapterFactory.build") as build:
        with pytest.raises(OrderRejected, match="Kill switch actif"):
            ExecutionOrchestrator.submit_order(order)

    build.assert_not_called()
    order.refresh_from_db()
    assert order.status == "REJECTED"


def test_async_submit_honours_portfolio_kill_switch(
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
        symbol="CANONUSD",
        side="BUY",
        mode="PAPER",
        status="PENDING_SUBMIT",
        requested_quantity=Decimal("1"),
        approved_quantity=Decimal("1"),
        requested_stake_amount=Decimal("100"),
        approved_notional=Decimal("100"),
        requested_price=Decimal("100"),
        idempotency_key="async-portfolio-kill-switch",
    )

    with mock.patch(
        "execution.tasks.RiskGuardService.has_active_kill_switch",
        return_value=True,
    ), mock.patch("execution.adapters.factory.BrokerAdapterFactory.build") as build:
        result = submit_order_to_broker_task.run(order.id)

    build.assert_not_called()
    order.refresh_from_db()
    assert result == {"ok": False, "err": "portfolio_kill_switch"}
    assert order.status == "REJECTED"


def test_live_intent_launch_creates_explicit_deployment(
    user,
    connected_live_broker,
    portfolio_live,
):
    from market.models import Asset, Timeframe
    from strategies.models import StrategyDeployment
    from trading.models import TradingIntent
    from trading.services.execution.base_execution import IntentExecutionService

    asset = Asset.objects.create(
        name="Intent Asset",
        symbol="INTENTUSD",
        asset_class="CRYPTO",
        exchange="TEST",
    )
    Timeframe.objects.create(code="intent-15m", label="Intent 15 minutes", minutes=15)
    intent = TradingIntent.objects.create(
        user=user,
        broker_account=connected_live_broker,
        portfolio=portfolio_live,
        title="Mission live canonique",
        capital_amount=Decimal("1000"),
        target_return_percent=10,
        max_loss_percent=5,
        duration_days=7,
        execution_mode="LIVE",
        status="PLANNED",
        ai_plan={
            "strategy_type": "HYBRID",
            "asset_universe": [asset.symbol],
            "timeframe": "intent-15m",
            "min_confidence_threshold": 0.75,
            "risk_per_trade_percent": 1,
        },
    )

    IntentExecutionService.launch(intent)

    intent.refresh_from_db()
    intent.strategy.refresh_from_db()
    deployment = StrategyDeployment.objects.get(strategy=intent.strategy, user=user)
    assert intent.status == "RUNNING"
    assert intent.approved_by_user is True
    assert intent.strategy.status == "LIVE"
    assert deployment.status == "ACTIVE"
    assert deployment.portfolio_id == portfolio_live.id
    assert deployment.broker_account_id == connected_live_broker.id


@pytest.fixture
def connected_live_broker(broker_live):
    broker_live.last_connection_status = True
    broker_live.last_connected_at = timezone.now()
    broker_live.save(update_fields=[
        "last_connection_status",
        "last_connected_at",
        "updated_at",
    ])
    return broker_live


def test_filled_deriv_order_remains_in_contract_sync(
    user,
    broker_live,
    portfolio_live,
):
    from brokers.models_external_ref import BrokerExternalRef
    from execution.models import Order
    from trading.tasks import sync_execution_deriv_contracts_task

    order = Order.objects.create(
        user=user,
        portfolio=portfolio_live,
        broker_account=broker_live,
        symbol="R_100",
        side="BUY",
        mode="LIVE",
        status="FILLED",
        requested_quantity=Decimal("1"),
        approved_quantity=Decimal("1"),
        requested_stake_amount=Decimal("10"),
        approved_notional=Decimal("10"),
        broker_order_id="contract-filled-open",
        idempotency_key="filled-deriv-sync",
    )
    BrokerExternalRef.upsert(
        broker="DERIV",
        broker_account=broker_live,
        kind="CONTRACT",
        external_id=order.broker_order_id,
        internal_kind="ORDER",
        internal_id=order.id,
        last_status="open",
    )
    client = mock.MagicMock()
    client.list_options_accounts.return_value = {
        "data": [{"account_id": "demo-account", "account_type": "demo"}],
    }
    client.get_otp_ws_url.return_value = "wss://example.test"
    client.proposal_open_contract.return_value = {
        "proposal_open_contract": {
            "contract_id": order.broker_order_id,
            "status": "open",
            "is_sold": 0,
            "is_settleable": 0,
        },
    }

    with mock.patch("trading.tasks.DerivClient", return_value=client):
        result = sync_execution_deriv_contracts_task.run()

    assert result["total"] == 1
    assert result["updated"] == 1
    client.proposal_open_contract.assert_called_once_with(
        contract_id=order.broker_order_id,
    )


def test_execution_order_creation_has_single_production_writer():
    production_files = [
        path
        for path in PROJECT_ROOT.rglob("*.py")
        if "venv" not in path.parts
        and "migrations" not in path.parts
        and "tests_phase" not in path.parts
    ]
    writer_files = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in production_files
        if "Order.objects.create(" in path.read_text(encoding="utf-8")
        or "ExecutionOrder.objects.create(" in path.read_text(encoding="utf-8")
    }
    assert writer_files == {"execution/services.py"}


def test_trading_execution_package_cannot_call_brokers_directly():
    forbidden = (
        "mt5.order_send",
        "create_market_order(",
        "DerivClient(",
        "ws_client.buy(",
        "from trading.models import Order",
    )
    package = PROJECT_ROOT / "trading" / "services" / "execution"
    violations = []
    for path in package.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in source:
                violations.append(f"{path.name}: {token}")
    assert violations == []


def test_legacy_order_interfaces_are_read_only():
    forms_source = (PROJECT_ROOT / "trading" / "forms.py").read_text(encoding="utf-8")
    serializers_source = (
        PROJECT_ROOT / "trading" / "serializers.py"
    ).read_text(encoding="utf-8")
    assert "class OrderForm" not in forms_source
    assert "HistoricalReadOnlySerializer" in serializers_source
