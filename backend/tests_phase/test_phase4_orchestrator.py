"""
Tests Phase 4 — ExecutionOrchestrator
- Idempotence (même idempotency_key → même Order)
- RiskEngine.evaluate appelé obligatoirement
- Kill switch FEATURE_TRADING_ENABLED=False bloque
"""

from decimal import Decimal
from unittest import mock

import pytest
from django.contrib.auth import get_user_model

from brokers.models import BrokerAccount
from execution.intents import OrderIntent
from execution.models import Order
from execution.orchestrator import (
    ExecutionOrchestrator,
    OrderRejected,
    TradingDisabled,
)
from portfolio.models import Portfolio


User = get_user_model()


@pytest.fixture
def setup(db):
    user = User.objects.create_user(username="exec", password="x")
    broker = BrokerAccount.objects.create(
        user=user, broker="DERIV", name="demo", deriv_app_id="1089", is_active=True,
    )
    portfolio = Portfolio.objects.create(
        user=user, broker_account=broker, name="main",
        starting_balance=Decimal("10000.00"),
        current_balance=Decimal("10000.00"),
        available_cash=Decimal("10000.00"),
    )
    return user, broker, portfolio


@pytest.fixture
def fake_decision_approved():
    """Patch RiskEngine.evaluate pour retourner une décision approved."""
    class _Decision:
        approved = True
        approved_quantity = Decimal("1")
        approved_notional = Decimal("100")
        reason = ""

    with mock.patch("risk.engine.RiskEngine.evaluate", return_value=_Decision()):
        yield


@pytest.fixture
def fake_decision_rejected():
    class _Decision:
        approved = False
        approved_quantity = Decimal("0")
        approved_notional = Decimal("0")
        reason = "max_risk_per_trade_exceeded"

    with mock.patch("risk.engine.RiskEngine.evaluate", return_value=_Decision()):
        yield


@pytest.mark.django_db
def test_idempotent_replay(setup, fake_decision_approved):
    user, broker, portfolio = setup

    intent = OrderIntent(
        user_id=user.id, portfolio_id=portfolio.id, broker_account_id=broker.id,
        symbol="EURUSD", side="BUY", requested_quantity=Decimal("1"),
        idempotency_key="repeat-1", mode="PAPER",
    )

    o1 = ExecutionOrchestrator.submit(intent)
    o2 = ExecutionOrchestrator.submit(intent)

    assert o1.id == o2.id
    assert Order.objects.filter(idempotency_key="repeat-1").count() == 1


@pytest.mark.django_db
def test_risk_rejection_raises(setup, fake_decision_rejected):
    user, broker, portfolio = setup

    intent = OrderIntent(
        user_id=user.id, portfolio_id=portfolio.id, broker_account_id=broker.id,
        symbol="EURUSD", side="BUY", requested_quantity=Decimal("1"),
        idempotency_key="rejected-1", mode="LIVE",
    )

    with pytest.raises(OrderRejected) as exc:
        ExecutionOrchestrator.submit(intent)
    assert "max_risk_per_trade_exceeded" in str(exc.value)
    assert Order.objects.filter(idempotency_key="rejected-1").count() == 0


@pytest.mark.django_db
def test_kill_switch_blocks(settings, setup, fake_decision_approved):
    settings.FEATURE_TRADING_ENABLED = False
    user, broker, portfolio = setup

    intent = OrderIntent(
        user_id=user.id, portfolio_id=portfolio.id, broker_account_id=broker.id,
        symbol="EURUSD", side="BUY", requested_quantity=Decimal("1"),
        idempotency_key="kill-1", mode="LIVE",
    )

    with pytest.raises(TradingDisabled):
        ExecutionOrchestrator.submit(intent)
    assert Order.objects.filter(idempotency_key="kill-1").count() == 0
