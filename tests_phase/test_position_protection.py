from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone


pytestmark = pytest.mark.django_db


def _position(portfolio, broker, *, current="100", stop="95", target="110"):
    from portfolio.models import Position

    return Position.objects.create(
        portfolio=portfolio,
        broker_account=broker,
        symbol="BTCUSDT",
        side="LONG",
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        average_entry_price=Decimal("100"),
        current_price=Decimal(current),
        stop_loss=Decimal(stop) if stop is not None else None,
        take_profit=Decimal(target) if target is not None else None,
        status="OPEN",
        source="STRATEGY",
    )


def test_paper_protection_is_active_but_live_deriv_is_explicitly_disabled(
    portfolio_paper,
    broker_paper,
    portfolio_live,
    broker_live,
):
    from execution.protection import PositionProtectionService

    paper = PositionProtectionService.sync_from_position(
        _position(portfolio_paper, broker_paper)
    )
    live = PositionProtectionService.sync_from_position(
        _position(portfolio_live, broker_live)
    )

    assert paper.mode == "LOCAL_MONITORED"
    assert paper.status == "ACTIVE"
    assert live.mode == "UNSUPPORTED"
    assert live.status == "DISABLED"
    assert live.metadata["capability_reason"] == "deriv_contract_protection_not_configured"


def test_invalid_protection_levels_are_disabled(portfolio_paper, broker_paper):
    from execution.protection import PositionProtectionService

    position = _position(
        portfolio_paper,
        broker_paper,
        stop="105",
        target="90",
    )
    protection = PositionProtectionService.sync_from_position(position)

    assert protection.status == "DISABLED"
    assert protection.last_error == "long_stop_loss_must_be_below_entry"


def test_trailing_stop_only_moves_in_favourable_direction(
    portfolio_paper,
    broker_paper,
):
    from execution.protection import PositionProtectionService
    from portfolio.models import Position

    position = _position(
        portfolio_paper,
        broker_paper,
        current="120",
        stop="95",
        target=None,
    )
    order = SimpleNamespace(
        id=42,
        metadata={
            "trailing_stop_enabled": True,
            "trail_percent": "0.015",
        },
    )
    protection = PositionProtectionService.sync_from_position(position, order=order)

    first = PositionProtectionService.evaluate(protection.id)
    protection.refresh_from_db()
    first_stop = protection.stop_loss

    Position.objects.filter(pk=position.pk).update(
        current_price=Decimal("119"),
        updated_at=timezone.now(),
    )
    second = PositionProtectionService.evaluate(protection.id)
    protection.refresh_from_db()

    assert first["status"] == "active"
    assert second["status"] == "active"
    assert first_stop > Decimal("118")
    assert protection.stop_loss == first_stop


def test_stale_price_never_triggers_a_close(settings, portfolio_paper, broker_paper):
    from execution.models import Order
    from execution.protection import PositionProtectionService
    from portfolio.models import Position

    settings.POSITION_PROTECTION_MAX_PRICE_AGE_SECONDS = 5
    position = _position(portfolio_paper, broker_paper, current="90")
    Position.objects.filter(pk=position.pk).update(
        updated_at=timezone.now() - timedelta(minutes=2)
    )
    protection = PositionProtectionService.sync_from_position(position)
    Position.objects.filter(pk=position.pk).update(
        updated_at=timezone.now() - timedelta(minutes=2)
    )

    result = PositionProtectionService.evaluate(protection.id)

    assert result == {"status": "skipped", "reason": "stale_or_missing_market_price"}
    assert not Order.objects.filter(closes_position=position).exists()


def test_take_profit_closes_paper_position_once_and_preserves_cash_pnl(
    user,
    portfolio_paper,
    broker_paper,
):
    from core.models import OutboxEvent
    from execution.models import Order, PositionProtection
    from execution.protection import PositionProtectionService
    from execution.tasks import submit_order_to_broker_task
    from portfolio.models import CashLedgerEntry, Position
    from portfolio.models_trade import Trade

    opening_order = Order.objects.create(
        user=user,
        portfolio=portfolio_paper,
        broker_account=broker_paper,
        symbol="BTCUSDT",
        side="BUY",
        requested_quantity=Decimal("1"),
        approved_quantity=Decimal("1"),
        requested_stake_amount=Decimal("100"),
        approved_notional=Decimal("100"),
        requested_price=Decimal("100"),
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        idempotency_key="protection-opening-order",
    )

    with mock.patch("core.outbox._nudge_publisher"):
        open_result = submit_order_to_broker_task(opening_order.id)
        position = Position.objects.get(portfolio=portfolio_paper, symbol="BTCUSDT")
        protection = PositionProtection.objects.get(position=position)
        Position.objects.filter(pk=position.pk).update(
            current_price=Decimal("110"),
            updated_at=timezone.now(),
        )
        trigger_result = PositionProtectionService.evaluate(protection.id)
        repeated_result = PositionProtectionService.evaluate(protection.id)

    assert open_result["ok"] is True
    assert trigger_result["status"] == "triggered"
    assert repeated_result["status"] == "skipped"
    assert Order.objects.filter(closes_position=position).count() == 1
    assert OutboxEvent.objects.filter(
        idempotency_key=f"order:{trigger_result['order_id']}:submit"
    ).exists()

    with mock.patch("core.outbox._nudge_publisher"):
        close_result = submit_order_to_broker_task(trigger_result["order_id"])

    position.refresh_from_db()
    protection.refresh_from_db()
    portfolio_paper.refresh_from_db()
    trade = Trade.objects.get(position=position)
    cash_movements = list(
        CashLedgerEntry.objects
        .filter(portfolio=portfolio_paper, entry_type="TRADE_EXECUTION")
        .order_by("created_at")
        .values_list("amount", flat=True)
    )

    assert close_result["ok"] is True
    assert position.status == "CLOSED"
    assert protection.status == "COMPLETED"
    assert trade.realized_pnl == Decimal("10.00")
    assert cash_movements == [Decimal("-100.00"), Decimal("110.00")]
    assert portfolio_paper.current_balance == Decimal("10010.00")


def test_only_one_active_close_order_is_allowed(
    user,
    portfolio_paper,
    broker_paper,
):
    from execution.models import Order

    position = _position(portfolio_paper, broker_paper)
    common = {
        "user": user,
        "portfolio": portfolio_paper,
        "broker_account": broker_paper,
        "closes_position": position,
        "symbol": position.symbol,
        "side": "SELL",
        "approved_quantity": Decimal("1"),
        "approved_notional": Decimal("100"),
        "requested_price": Decimal("100"),
        "metadata": {"reduce_only": True},
    }
    Order.objects.create(idempotency_key="close-reservation-1", **common)

    with pytest.raises(IntegrityError), transaction.atomic():
        Order.objects.create(idempotency_key="close-reservation-2", **common)


def test_reduce_only_failure_never_releases_unlocked_cash(
    user,
    portfolio_live,
    broker_live,
):
    from execution.models import Order
    from execution.tasks import submit_order_to_broker_task
    from portfolio.models import CashLedgerEntry

    position = _position(portfolio_live, broker_live)
    order = Order.objects.create(
        user=user,
        portfolio=portfolio_live,
        broker_account=broker_live,
        closes_position=position,
        symbol=position.symbol,
        side="SELL",
        approved_quantity=Decimal("1"),
        approved_notional=Decimal("100"),
        requested_price=Decimal("100"),
        idempotency_key="failed-live-reduce-only",
        metadata={"reduce_only": True},
    )
    adapter = mock.Mock()
    adapter.close_position.side_effect = ValueError("broker rejected close")

    with mock.patch(
        "execution.adapters.factory.BrokerAdapterFactory.build",
        return_value=adapter,
    ), mock.patch("core.outbox._nudge_publisher"):
        result = submit_order_to_broker_task(order.id)

    order.refresh_from_db()
    assert result["ok"] is False
    assert order.status == "FAILED"
    assert not CashLedgerEntry.objects.filter(
        portfolio=portfolio_live,
        entry_type="ORDER_RELEASE",
        reference_id=str(order.id),
    ).exists()
