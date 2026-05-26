"""
Tests Phase 2 — TransferService Wallet ↔ Portfolio
- Atomicité (debit + credit dans la même transaction)
- Idempotence (même request_id → même Transfer renvoyé)
- Cohérence cross-table
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from accounting.models import Transfer
from accounting.services import TransferService, TransferError
from brokers.models import BrokerAccount
from portfolio.models import Portfolio
from wallet.models import Wallet


User = get_user_model()


@pytest.fixture
def setup(db):
    user = User.objects.create_user(username="bob", password="x")
    wallet = Wallet.objects.create(
        user=user, currency="USD",
        available_balance=Decimal("500.00"),
    )
    broker = BrokerAccount.objects.create(
        user=user, broker="DERIV", name="demo", is_active=True,
    )
    portfolio = Portfolio.objects.create(
        user=user, broker_account=broker, name="main",
        starting_balance=Decimal("1000.00"),
    )
    return user, wallet, portfolio


@pytest.mark.django_db
def test_transfer_wallet_to_portfolio_ok(setup):
    user, wallet, portfolio = setup

    transfer = TransferService.transfer_wallet_to_portfolio(
        wallet_id=wallet.id,
        portfolio_id=portfolio.id,
        amount=Decimal("200"),
        request_id="req-1",
    )

    assert transfer.status == "COMPLETED"
    wallet.refresh_from_db()
    portfolio.refresh_from_db()

    assert wallet.available_balance == Decimal("300.00")
    assert portfolio.current_balance == Decimal("1200.00")


@pytest.mark.django_db
def test_transfer_idempotent(setup):
    user, wallet, portfolio = setup

    t1 = TransferService.transfer_wallet_to_portfolio(
        wallet_id=wallet.id,
        portfolio_id=portfolio.id,
        amount=Decimal("100"),
        request_id="req-idemp",
    )
    t2 = TransferService.transfer_wallet_to_portfolio(
        wallet_id=wallet.id,
        portfolio_id=portfolio.id,
        amount=Decimal("100"),
        request_id="req-idemp",
    )

    assert t1.id == t2.id
    assert Transfer.objects.filter(request_id="req-idemp").count() == 1
    wallet.refresh_from_db()
    assert wallet.available_balance == Decimal("400.00")  # 100 débité une seule fois


@pytest.mark.django_db
def test_transfer_blocks_on_insufficient(setup):
    user, wallet, portfolio = setup

    with pytest.raises(TransferError):
        TransferService.transfer_wallet_to_portfolio(
            wallet_id=wallet.id,
            portfolio_id=portfolio.id,
            amount=Decimal("9999"),
            request_id="req-too-big",
        )

    wallet.refresh_from_db()
    portfolio.refresh_from_db()
    assert wallet.available_balance == Decimal("500.00")  # rien bougé
    assert Transfer.objects.get(request_id="req-too-big").status == "FAILED"
