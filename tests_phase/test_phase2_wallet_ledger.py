"""
Tests Phase 2 — WalletLedgerService
- Idempotence du credit / debit
- Concurrence sur lock_funds_for_withdrawal
- Replay du ledger reconstitue la balance
"""

from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.contrib.auth import get_user_model
from django.db import connection

from wallet.models import Wallet, WalletLedgerEntry
from wallet.services_v2 import WalletLedgerService, InsufficientFundsError


User = get_user_model()


@pytest.fixture
def wallet(db):
    user = User.objects.create_user(username="alice", password="x")
    # Le wallet est auto-créé par signal post_save(User) : on le met à jour
    w, _ = Wallet.objects.get_or_create(user=user, defaults={"currency": "USD"})
    Wallet.objects.filter(pk=w.pk).update(
        currency="USD",
        available_balance=Decimal("100.00"),
        locked_balance=Decimal("0.00"),
    )
    w.refresh_from_db()
    return w


@pytest.mark.django_db
def test_credit_idempotent(wallet):
    """
    5 appels avec le même external_event_id → 1 seule entry, balance +50.
    """
    for _ in range(5):
        WalletLedgerService.credit(
            wallet_id=wallet.id,
            amount=Decimal("50"),
            external_event_id="stripe:evt_123",
        )

    wallet.refresh_from_db()
    assert wallet.available_balance == Decimal("150.00")
    assert WalletLedgerEntry.objects.filter(
        wallet=wallet, entry_type="CREDIT",
    ).count() == 1


@pytest.mark.django_db
def test_debit_blocks_on_insufficient_funds(wallet):
    with pytest.raises(InsufficientFundsError):
        WalletLedgerService.debit(
            wallet_id=wallet.id,
            amount=Decimal("999"),
            external_event_id="evt_too_big",
        )
    wallet.refresh_from_db()
    assert wallet.available_balance == Decimal("100.00")


@pytest.mark.django_db(transaction=True)
def test_concurrent_locks_no_overdraft(wallet):
    """
    20 threads tentent de lock 10 chacun (= 200 demandé) sur 100 disponibles.
    Au final : exactement 10 réussissent (100 lockés), 10 InsufficientFunds.
    """
    from django.db import connection
    if connection.vendor != "postgresql":
        pytest.skip("Test de concurrence : nécessite PostgreSQL (SQLite = writer unique).")

    def attempt(i):
        try:
            WalletLedgerService.lock(
                wallet_id=wallet.id,
                amount=Decimal("10"),
                external_event_id=f"lock-{i}",
            )
            return "OK"
        except InsufficientFundsError:
            return "INSUFFICIENT"
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(attempt, range(20)))

    n_ok = results.count("OK")
    assert n_ok == 10, f"expected 10 OK, got {n_ok}, results={results}"

    wallet.refresh_from_db()
    assert wallet.available_balance == Decimal("0.00")
    assert wallet.locked_balance == Decimal("100.00")
