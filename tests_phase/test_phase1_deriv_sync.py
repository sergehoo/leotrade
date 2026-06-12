"""
Tests Phase 1 — Sync Deriv (handlers idempotents)
- on_balance_update : 2x même snapshot → 1 seul ledger entry
- on_open_contract_update : closed contract → fill + Trade créés
- BrokerExternalRef.upsert : update_or_create idempotent
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from brokers.models import BrokerAccount
from brokers.models_external_ref import BrokerExternalRef
from brokers.services.deriv_sync import (
    on_balance_update,
    on_open_contract_update,
)
from execution.models import ExecutionFill, Order
from portfolio.models import CashLedgerEntry, Portfolio
from portfolio.models_trade import Trade


User = get_user_model()


@pytest.fixture
def setup(db):
    user = User.objects.create_user(username="deriv_user", password="x")
    broker = BrokerAccount.objects.create(
        user=user, broker="DERIV", name="demo", deriv_app_id="1089", is_active=True,
    )
    portfolio = Portfolio.objects.create(
        user=user, broker_account=broker, name="main",
        starting_balance=Decimal("0.00"),
        current_balance=Decimal("0.00"),
        is_default=True,
    )
    return user, broker, portfolio


@pytest.mark.django_db
def test_balance_update_idempotent(setup):
    user, broker, portfolio = setup

    payload = {"balance": "1234.56", "currency": "USD", "id": "snap-1"}
    on_balance_update(broker_account_id=broker.id, payload=payload)
    on_balance_update(broker_account_id=broker.id, payload=payload)

    portfolio.refresh_from_db()
    n_entries = CashLedgerEntry.objects.filter(
        portfolio=portfolio, entry_type="BROKER_IMPORT",
    ).count()
    assert n_entries == 1


@pytest.mark.django_db
def test_external_ref_upsert(setup):
    user, broker, portfolio = setup

    BrokerExternalRef.upsert(
        broker="DERIV", broker_account=broker, kind="CONTRACT",
        external_id="123", internal_kind="ORDER", internal_id="42",
        last_status="open",
    )
    BrokerExternalRef.upsert(
        broker="DERIV", broker_account=broker, kind="CONTRACT",
        external_id="123", internal_kind="ORDER", internal_id="42",
        last_status="won",
    )

    refs = BrokerExternalRef.objects.filter(
        broker="DERIV", kind="CONTRACT", external_id="123",
    )
    assert refs.count() == 1
    assert refs.first().last_status == "won"


@pytest.mark.django_db
def test_closed_contract_creates_fill_and_trade(setup):
    user, broker, portfolio = setup

    # 1. Crée un Order interne pour Deriv
    order = Order.objects.create(
        user=user, portfolio=portfolio, broker_account=broker,
        symbol="R_100", side="BUY", order_type="MARKET",
        approved_quantity=Decimal("1"), approved_notional=Decimal("10.00"),
        status="SUBMITTED",
        idempotency_key="deriv-1",
        mode="LIVE",
    )
    BrokerExternalRef.upsert(
        broker="DERIV", broker_account=broker, kind="CONTRACT",
        external_id="contract_999",
        internal_kind="ORDER", internal_id=str(order.id),
        last_status="open",
    )

    # 2. Reçoit l'event "won"
    payload = {
        "contract_id": "contract_999",
        "is_sold": 1, "is_settleable": 0,
        "status": "won",
        "buy_price": "10.00", "sell_price": "12.50", "profit": "2.50",
        "currency": "USD",
        "transaction_ids": {"sell": "tx_close_1"},
    }
    on_open_contract_update(broker_account_id=broker.id, payload=payload)

    # 3. Vérifie qu'un fill a été créé
    assert ExecutionFill.objects.filter(
        order=order, broker_fill_id="tx_close_1",
    ).count() == 1

    # 4. Idempotence : rejouer le même event ne crée pas de doublon
    on_open_contract_update(broker_account_id=broker.id, payload=payload)
    assert ExecutionFill.objects.filter(
        order=order, broker_fill_id="tx_close_1",
    ).count() == 1
