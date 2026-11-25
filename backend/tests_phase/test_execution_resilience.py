from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import pytest
from django.db import connection
from django.utils import timezone


def _order(*, user, portfolio, broker, status, key):
    from execution.models import Order

    return Order.objects.create(
        user=user,
        portfolio=portfolio,
        broker_account=broker,
        symbol="R_100",
        side="BUY",
        order_type="MARKET",
        mode=broker.mode,
        status=status,
        requested_quantity=Decimal("1"),
        approved_quantity=Decimal("1"),
        requested_stake_amount=Decimal("10.00"),
        approved_notional=Decimal("10.00"),
        requested_price=Decimal("10.00"),
        idempotency_key=key,
    )


@pytest.mark.django_db
def test_redis_outage_blocks_mutation_before_broker_call(broker_paper):
    from infrastructure.broker_clients.gateway import (
        BrokerGateway,
        CircuitStateUnavailableError,
    )

    client = mock.Mock()
    gateway = BrokerGateway(broker_paper, client=client)

    with mock.patch(
        "infrastructure.broker_clients.gateway.cache.get",
        side_effect=ConnectionError("redis down"),
    ):
        with pytest.raises(CircuitStateUnavailableError, match="avant envoi"):
            gateway.submit_order(object())

    client.submit_order.assert_not_called()


@pytest.mark.django_db
def test_broker_client_is_not_built_before_mutation_preflight(broker_paper):
    from infrastructure.broker_clients.gateway import (
        BrokerGateway,
        CircuitStateUnavailableError,
    )

    with mock.patch(
        "infrastructure.broker_clients.gateway.cache.get",
        side_effect=ConnectionError("redis down"),
    ), mock.patch(
        "infrastructure.broker_clients.gateway.BrokerClientFactory.build"
    ) as build_client:
        gateway = BrokerGateway(broker_paper)
        with pytest.raises(CircuitStateUnavailableError):
            gateway.submit_order(object())

    build_client.assert_not_called()


@pytest.mark.django_db
def test_redis_outage_keeps_safe_broker_reads_available(broker_paper):
    from infrastructure.broker_clients.gateway import BrokerGateway

    client = mock.Mock()
    client.fetch_balances.return_value = [{"currency": "USD"}]
    gateway = BrokerGateway(broker_paper, client=client)

    with mock.patch(
        "infrastructure.broker_clients.gateway.cache.get",
        side_effect=ConnectionError("redis down"),
    ):
        result = gateway.fetch_balances()

    assert result == [{"currency": "USD"}]
    client.fetch_balances.assert_called_once_with()


def test_retryable_detection_unwraps_network_error_but_honours_explicit_veto():
    from core.retry import is_retryable_exception
    from infrastructure.broker_clients.gateway import CircuitStateUnavailableError

    try:
        try:
            raise TimeoutError("socket timeout")
        except TimeoutError as exc:
            raise RuntimeError("broker wrapper") from exc
    except RuntimeError as wrapped:
        assert is_retryable_exception(wrapped) is True

    try:
        try:
            raise ConnectionError("redis down")
        except ConnectionError as exc:
            raise CircuitStateUnavailableError("preflight") from exc
    except CircuitStateUnavailableError as vetoed:
        assert is_retryable_exception(vetoed) is False


def test_binance_targeted_lookup_recovers_individual_trades():
    from infrastructure.broker_clients.binance_client import BinanceBrokerClient

    client = object.__new__(BinanceBrokerClient)
    client.client = mock.Mock()
    client.client.get_order.return_value = {
        "orderId": 42,
        "clientOrderId": "stable-client-id",
        "symbol": "BTCUSDT",
        "status": "FILLED",
        "executedQty": "0.10",
        "cummulativeQuoteQty": "10.00",
        "updateTime": 1_700_000_000_000,
    }
    client.client.get_my_trades.return_value = [{
        "id": 7,
        "qty": "0.10",
        "price": "100.00",
        "quoteQty": "10.00",
        "commission": "0.01",
        "commissionAsset": "USDT",
        "time": 1_700_000_000_000,
        "isMaker": False,
    }]
    order = SimpleNamespace(
        broker_order_id=None,
        idempotency_key="stable-client-id",
        symbol="BTCUSDT",
        portfolio=SimpleNamespace(base_currency="USDT"),
    )

    payload = client.fetch_order(order)

    assert payload["status"] == "FILLED"
    assert payload["broker_order_id"] == "42"
    assert payload["fills"][0]["broker_fill_id"] == "7"
    assert payload["fills"][0]["notional"] == Decimal("10.00")
    client.client.get_order.assert_called_once_with(
        symbol="BTCUSDT",
        origClientOrderId="stable-client-id",
    )


@pytest.mark.django_db
def test_deriv_targeted_lookup_recovers_contract_from_external_reference(
    user,
    broker_live,
    portfolio_live,
):
    from brokers.models_external_ref import BrokerExternalRef
    from infrastructure.broker_clients.deriv_client import DerivBrokerClient

    order = _order(
        user=user,
        portfolio=portfolio_live,
        broker=broker_live,
        status="UNKNOWN_BROKER_STATE",
        key="deriv-targeted-contract",
    )
    BrokerExternalRef.upsert(
        broker="DERIV",
        broker_account=broker_live,
        kind="CONTRACT",
        external_id="987654",
        internal_kind="ORDER",
        internal_id=order.id,
    )
    client = object.__new__(DerivBrokerClient)
    client.broker_account = broker_live
    ws = mock.Mock()
    ws.proposal_open_contract.return_value = {
        "proposal_open_contract": {
            "contract_id": 987654,
            "underlying": "R_100",
            "buy_price": "10.00",
            "status": "open",
            "transaction_ids": {"buy": 123456},
        }
    }
    client._open_authenticated_ws = mock.Mock(return_value=ws)

    payload = client.fetch_order(order)

    assert payload["status"] == "FILLED"
    assert payload["broker_order_id"] == "987654"
    assert payload["fills"][0]["broker_fill_id"] == "123456"
    ws.proposal_open_contract.assert_called_once_with(contract_id="987654")
    ws.close.assert_called_once_with()


@pytest.mark.django_db
def test_cash_reservation_lock_and_release_are_idempotent(portfolio_live):
    from portfolio.models import CashLedgerEntry
    from portfolio.services import PortfolioAccountingService

    original_available = portfolio_live.available_cash
    kwargs = {
        "portfolio": portfolio_live,
        "amount": Decimal("250.00"),
        "reference_type": "ORDER",
        "reference_id": "resilience-order-1",
    }

    PortfolioAccountingService.lock_cash_for_order(**kwargs)
    PortfolioAccountingService.lock_cash_for_order(**kwargs)
    assert CashLedgerEntry.objects.filter(
        portfolio=portfolio_live,
        entry_type="ORDER_LOCK",
        reference_id="resilience-order-1",
    ).count() == 1

    PortfolioAccountingService.release_cash_from_order(**kwargs)
    PortfolioAccountingService.release_cash_from_order(**kwargs)
    assert CashLedgerEntry.objects.filter(
        portfolio=portfolio_live,
        entry_type="ORDER_RELEASE",
        reference_id="resilience-order-1",
    ).count() == 1

    portfolio_live.refresh_from_db()
    assert portfolio_live.locked_cash == Decimal("0.00")
    assert portfolio_live.available_cash == original_available


@pytest.mark.django_db
def test_cache_preflight_failure_releases_cash_without_unknown_state(
    user,
    broker_live,
    portfolio_live,
):
    from execution.tasks import submit_order_to_broker_task
    from infrastructure.broker_clients.gateway import CircuitStateUnavailableError
    from portfolio.services import PortfolioAccountingService

    order = _order(
        user=user,
        portfolio=portfolio_live,
        broker=broker_live,
        status="PENDING_SUBMIT",
        key="redis-preflight-order",
    )
    PortfolioAccountingService.lock_cash_for_order(
        portfolio=portfolio_live,
        amount=order.approved_notional,
        reference_type="ORDER",
        reference_id=str(order.id),
    )
    adapter = mock.Mock()
    adapter.submit_order.side_effect = CircuitStateUnavailableError("redis down")

    with mock.patch(
        "execution.adapters.factory.BrokerAdapterFactory.build",
        return_value=adapter,
    ), mock.patch("core.outbox._nudge_publisher"):
        result = submit_order_to_broker_task(order.id)

    order.refresh_from_db()
    portfolio_live.refresh_from_db()
    assert result["ok"] is False
    assert order.status == "FAILED"
    assert order.metadata.get("broker_state_unknown") is not True
    assert portfolio_live.locked_cash == Decimal("0.00")


@pytest.mark.django_db
def test_targeted_reconciliation_recovers_filled_order_missing_from_open_orders(
    user,
    broker_live,
    portfolio_live,
):
    from execution.reconciliation import BrokerReconciliationService
    from portfolio.services import PortfolioAccountingService

    order = _order(
        user=user,
        portfolio=portfolio_live,
        broker=broker_live,
        status="UNKNOWN_BROKER_STATE",
        key="targeted-filled-order",
    )
    PortfolioAccountingService.lock_cash_for_order(
        portfolio=portfolio_live,
        amount=order.approved_notional,
        reference_type="ORDER",
        reference_id=str(order.id),
    )
    gateway = mock.Mock()
    gateway.fetch_open_orders.return_value = []
    gateway.fetch_order.return_value = {
        "broker_order_id": "contract-recovered-1",
        "broker_client_order_id": "transaction-recovered-1",
        "symbol": order.symbol,
        "status": "FILLED",
        "fills": [{
            "broker_fill_id": "transaction-recovered-1",
            "quantity": Decimal("1"),
            "price": Decimal("10.00"),
            "notional": Decimal("10.00"),
            "fee": Decimal("0.00"),
        }],
        "raw": {"source": "targeted_lookup"},
    }

    with mock.patch(
        "execution.reconciliation.BrokerGateway",
        return_value=gateway,
    ), mock.patch("core.outbox._nudge_publisher"):
        sync_log = BrokerReconciliationService.reconcile_orders(portfolio_live)

    order.refresh_from_db()
    portfolio_live.refresh_from_db()
    assert sync_log.status == "SUCCESS"
    assert sync_log.payload["unmatched_local_orders_count"] == 0
    assert order.status == "FILLED"
    assert order.broker_order_id == "contract-recovered-1"
    assert order.fills.count() == 1
    assert portfolio_live.locked_cash == Decimal("0.00")
    gateway.fetch_order.assert_called_once()


@pytest.mark.django_db
def test_remote_terminal_state_releases_remaining_cash_once(
    user,
    broker_live,
    portfolio_live,
):
    from execution.reconciliation import BrokerReconciliationService
    from portfolio.models import CashLedgerEntry
    from portfolio.services import PortfolioAccountingService

    order = _order(
        user=user,
        portfolio=portfolio_live,
        broker=broker_live,
        status="SUBMITTED",
        key="targeted-cancel-order",
    )
    PortfolioAccountingService.lock_cash_for_order(
        portfolio=portfolio_live,
        amount=order.approved_notional,
        reference_type="ORDER",
        reference_id=str(order.id),
    )
    gateway = mock.Mock()
    gateway.fetch_open_orders.return_value = []
    gateway.fetch_order.return_value = {
        "broker_order_id": "cancelled-remote-1",
        "status": "CANCELLED",
        "fills": [],
        "raw": {"source": "targeted_lookup"},
    }

    with mock.patch(
        "execution.reconciliation.BrokerGateway",
        return_value=gateway,
    ), mock.patch("core.outbox._nudge_publisher"):
        BrokerReconciliationService.reconcile_orders(portfolio_live)
        BrokerReconciliationService.reconcile_orders(portfolio_live)

    order.refresh_from_db()
    portfolio_live.refresh_from_db()
    assert order.status == "CANCELLED"
    assert portfolio_live.locked_cash == Decimal("0.00")
    assert CashLedgerEntry.objects.filter(
        portfolio=portfolio_live,
        entry_type="ORDER_RELEASE",
        reference_id=str(order.id),
    ).count() == 1


@pytest.mark.django_db
def test_stale_live_submitting_order_is_never_replayed(
    user,
    broker_live,
    portfolio_live,
    settings,
):
    from core.models import OutboxEvent
    from execution.event_topics import PORTFOLIO_RECONCILE_REQUESTED
    from execution.tasks import recover_stale_execution_orders_task

    settings.EXECUTION_SUBMIT_STALE_SECONDS = 60
    settings.EXECUTION_UNKNOWN_ALERT_SECONDS = 3600
    order = _order(
        user=user,
        portfolio=portfolio_live,
        broker=broker_live,
        status="SUBMITTING",
        key="stale-live-submitting",
    )
    type(order).objects.filter(pk=order.pk).update(
        updated_at=timezone.now() - timedelta(minutes=5)
    )

    with mock.patch("core.outbox._nudge_publisher"):
        result = recover_stale_execution_orders_task()

    order.refresh_from_db()
    assert result["marked_unknown"] == 1
    assert result["requeued"] == 0
    assert order.status == "UNKNOWN_BROKER_STATE"
    assert OutboxEvent.objects.filter(
        topic=PORTFOLIO_RECONCILE_REQUESTED,
        aggregate_id=str(portfolio_live.id),
    ).exists()


@pytest.mark.django_db
def test_stale_paper_submitting_order_is_safely_requeued(
    user,
    broker_paper,
    portfolio_paper,
    settings,
):
    from core.models import OutboxEvent
    from execution.event_topics import ORDER_SUBMIT_REQUESTED
    from execution.tasks import recover_stale_execution_orders_task

    settings.EXECUTION_SUBMIT_STALE_SECONDS = 60
    order = _order(
        user=user,
        portfolio=portfolio_paper,
        broker=broker_paper,
        status="SUBMITTING",
        key="stale-paper-submitting",
    )
    type(order).objects.filter(pk=order.pk).update(
        updated_at=timezone.now() - timedelta(minutes=5)
    )

    with mock.patch("core.outbox._nudge_publisher"):
        result = recover_stale_execution_orders_task()

    order.refresh_from_db()
    assert result["requeued"] == 1
    assert order.status == "PENDING_SUBMIT"
    assert OutboxEvent.objects.filter(
        topic=ORDER_SUBMIT_REQUESTED,
        aggregate_id=str(order.id),
        payload__recovery=True,
    ).exists()


@pytest.mark.django_db
def test_unresolved_live_order_freezes_new_entries(
    user,
    broker_live,
    portfolio_live,
    risk_profile_live,
    settings,
):
    from execution.tasks import recover_stale_execution_orders_task
    from risk.services import RiskGuardService

    settings.EXECUTION_SUBMIT_STALE_SECONDS = 60
    settings.EXECUTION_UNKNOWN_ALERT_SECONDS = 120
    unknown_at = timezone.now() - timedelta(minutes=10)
    order = _order(
        user=user,
        portfolio=portfolio_live,
        broker=broker_live,
        status="UNKNOWN_BROKER_STATE",
        key="unknown-order-freeze",
    )
    type(order).objects.filter(pk=order.pk).update(
        metadata={"broker_state_unknown_at": unknown_at.isoformat()},
        updated_at=unknown_at,
    )

    with mock.patch("core.outbox._nudge_publisher"), mock.patch(
        "notifications.shortcuts.notify"
    ):
        result = recover_stale_execution_orders_task()

    assert result["frozen_portfolios"] == 1
    assert RiskGuardService.has_active_kill_switch(portfolio_live) is True


@pytest.mark.django_db
def test_kill_switch_trigger_is_idempotent(portfolio_live, risk_profile_live):
    from risk.services import RiskGuardService

    with mock.patch("notifications.shortcuts.notify"):
        first = RiskGuardService.trigger_kill_switch(
            portfolio_live,
            risk_profile_live,
            "BROKER_STATE_UNKNOWN",
            "first",
        )
        second = RiskGuardService.trigger_kill_switch(
            portfolio_live,
            risk_profile_live,
            "BROKER_STATE_UNKNOWN",
            "second",
        )

    assert first.id == second.id
    assert portfolio_live.kill_switch_events.filter(is_active=True).count() == 1


@pytest.mark.django_db(transaction=True)
def test_reconciliation_network_call_runs_outside_database_transaction(
    user,
    broker_live,
    portfolio_live,
):
    from execution.reconciliation import BrokerReconciliationService

    gateway = mock.Mock()

    def fetch_open_orders():
        assert connection.in_atomic_block is False
        return []

    gateway.fetch_open_orders.side_effect = fetch_open_orders
    with mock.patch(
        "execution.reconciliation.BrokerGateway",
        return_value=gateway,
    ):
        BrokerReconciliationService.reconcile_orders(portfolio_live)
