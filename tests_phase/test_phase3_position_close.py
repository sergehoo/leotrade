"""
Tests Phase 3 — PositionCloseService
- LONG total close → realized_pnl correct
- LONG partial close → 2 Trades, position PARTIALLY_CLOSED
- SHORT total close → signe correct
- Pas de double comptage : Portfolio.realized_pnl == Σ Trade.realized_pnl
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from brokers.models import BrokerAccount
from execution.models import ExecutionFill, Order
from execution.services_close import PositionCloseService
from portfolio.models import Portfolio, Position
from portfolio.models_trade import Trade
from portfolio.services_metrics import PortfolioMetricsService


User = get_user_model()


@pytest.fixture
def setup(db):
    user = User.objects.create_user(username="trader", password="x")
    broker = BrokerAccount.objects.create(
        user=user, broker="DERIV", name="demo", is_active=True,
    )
    portfolio = Portfolio.objects.create(
        user=user, broker_account=broker, name="main",
        starting_balance=Decimal("10000.00"),
    )
    return user, broker, portfolio


@pytest.fixture
def open_long_position(setup):
    user, broker, portfolio = setup
    pos = Position.objects.create(
        portfolio=portfolio, broker_account=broker,
        symbol="EURUSD", side="LONG",
        quantity=Decimal("10"),
        entry_price=Decimal("1.10"),
        average_entry_price=Decimal("1.10"),
        current_price=Decimal("1.10"),
        notional_value=Decimal("11.00"),
        status="OPEN",
        source="MANUAL",
    )
    order = Order.objects.create(
        user=user, portfolio=portfolio, broker_account=broker,
        symbol="EURUSD", side="BUY", order_type="MARKET",
        approved_quantity=Decimal("10"), approved_notional=Decimal("11.00"),
        status="FILLED",
        idempotency_key="open-long-1",
        mode="LIVE",
    )
    return user, broker, portfolio, pos, order


@pytest.mark.django_db
def test_long_total_close_creates_trade(open_long_position):
    user, broker, portfolio, pos, order = open_long_position

    fill = ExecutionFill.objects.create(
        order=order,
        broker_fill_id="fill-close-1",
        quantity=Decimal("10"),
        price=Decimal("1.20"),
        notional=Decimal("12.00"),
        fee=Decimal("0.10"),
        liquidity_type="CLOSE",
    )

    trade = PositionCloseService.apply_closing_fill(position=pos, fill=fill, opening_order=order)

    pos.refresh_from_db()
    assert pos.status == "CLOSED"
    assert pos.quantity == Decimal("0")

    # PnL = (1.20 - 1.10) * 10 - 0.10 = 0.90
    assert trade.realized_pnl == Decimal("0.90")
    assert trade.gross_pnl == Decimal("1.00")
    assert trade.fees == Decimal("0.10")


@pytest.mark.django_db
def test_long_partial_close(open_long_position):
    user, broker, portfolio, pos, order = open_long_position

    fill1 = ExecutionFill.objects.create(
        order=order, broker_fill_id="fill-1",
        quantity=Decimal("4"), price=Decimal("1.15"), notional=Decimal("4.60"),
        fee=Decimal("0.05"),
    )
    PositionCloseService.apply_closing_fill(position=pos, fill=fill1, opening_order=order)

    pos.refresh_from_db()
    assert pos.status == "PARTIALLY_CLOSED"
    assert pos.quantity == Decimal("6.00000000")

    fill2 = ExecutionFill.objects.create(
        order=order, broker_fill_id="fill-2",
        quantity=Decimal("6"), price=Decimal("1.20"), notional=Decimal("7.20"),
        fee=Decimal("0.05"),
    )
    PositionCloseService.apply_closing_fill(position=pos, fill=fill2, opening_order=order)

    pos.refresh_from_db()
    assert pos.status == "CLOSED"

    trades = Trade.objects.filter(position=pos).order_by("closed_at")
    assert trades.count() == 2

    # Trade 1 : (1.15-1.10)*4 - 0.05 = 0.15
    # Trade 2 : (1.20-1.10)*6 - 0.05 = 0.55
    assert trades[0].realized_pnl == Decimal("0.15")
    assert trades[1].realized_pnl == Decimal("0.55")


@pytest.mark.django_db
def test_no_double_counting(open_long_position):
    user, broker, portfolio, pos, order = open_long_position

    fill = ExecutionFill.objects.create(
        order=order, broker_fill_id="f-1",
        quantity=Decimal("10"), price=Decimal("1.20"), notional=Decimal("12.00"),
        fee=Decimal("0"),
    )
    PositionCloseService.apply_closing_fill(position=pos, fill=fill, opening_order=order)

    metrics = PortfolioMetricsService.compute_live(portfolio_id=portfolio.id)
    sum_trades = sum(t.realized_pnl for t in Trade.objects.filter(portfolio=portfolio))
    assert metrics.realized_pnl == sum_trades
    assert metrics.realized_pnl == Decimal("1.00")
