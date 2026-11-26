"""
tests_phase/test_wallet_reconciliation.py
=========================================

Rapprochement solde ↔ grand livre.

`WalletLedgerService` énonce une règle d'or — rien en dehors de lui ne
modifie `available_balance` — mais rien ne la vérifiait. Un solde posé
directement sur le champ restait invisible. Ces tests figent le contrôle
qui le rend détectable.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from wallet.models import Wallet, WalletLedgerEntry
from wallet.services_reconciliation import WalletReconciliationService

User = get_user_model()


def _wallet_for(username: str) -> Wallet:
    """Le portefeuille est créé automatiquement à l'inscription : on le
    récupère au lieu d'en créer un second, que la contrainte OneToOne
    rejetterait."""
    user = User.objects.create_user(
        username=username, email=f"{username}@leotrade.test", password="StrongPass123!",
    )
    wallet, _ = Wallet.objects.get_or_create(user=user, defaults={"currency": "USD"})
    return wallet


@pytest.fixture
def wallet(db):
    return _wallet_for("reco")


def _entry(wallet, entry_type, amount, before, after):
    return WalletLedgerEntry.objects.create(
        wallet=wallet,
        entry_type=entry_type,
        amount=Decimal(amount),
        balance_before=Decimal(before),
        balance_after=Decimal(after),
        currency=wallet.currency,
    )


@pytest.mark.django_db
class TestBalancedWallets:

    def test_an_empty_wallet_is_balanced(self, wallet):
        result = WalletReconciliationService.reconcile(wallet)

        assert result.is_balanced
        assert result.unexplained_amount == Decimal("0.00")

    def test_a_wallet_whose_chain_matches_is_balanced(self, wallet):
        _entry(wallet, "CREDIT", "500.00", "0.00", "500.00")
        _entry(wallet, "DEBIT", "200.00", "500.00", "300.00")
        Wallet.objects.filter(pk=wallet.pk).update(available_balance=Decimal("300.00"))
        wallet.refresh_from_db()

        result = WalletReconciliationService.reconcile(wallet)

        assert result.is_balanced, result.summary()
        assert result.entry_count == 2

    def test_locked_funds_count_towards_the_total(self, wallet):
        """`balance_before`/`after` portent le TOTAL, verrouillé compris :
        ignorer `locked_balance` ferait passer un verrouillage pour une fuite."""
        _entry(wallet, "CREDIT", "1000.00", "0.00", "1000.00")
        _entry(wallet, "LOCK", "400.00", "1000.00", "1000.00")
        Wallet.objects.filter(pk=wallet.pk).update(
            available_balance=Decimal("600.00"), locked_balance=Decimal("400.00"),
        )
        wallet.refresh_from_db()

        result = WalletReconciliationService.reconcile(wallet)

        assert result.is_balanced, result.summary()
        assert result.balance_total == Decimal("1000.00")


@pytest.mark.django_db
class TestUnbalancedWallets:

    def test_a_balance_written_outside_the_ledger_is_detected(self, wallet):
        """Le cas réellement observé en base : 20 000 USD, aucune écriture.

        C'est exactement ce qu'un solde posé par le shell, l'admin ou une
        fixture produit — et ce que rien ne détectait.
        """
        Wallet.objects.filter(pk=wallet.pk).update(available_balance=Decimal("20000.00"))
        wallet.refresh_from_db()

        result = WalletReconciliationService.reconcile(wallet)

        assert not result.is_balanced
        assert result.entry_count == 0
        assert result.closing_gap == Decimal("20000.00")
        assert result.unexplained_amount == Decimal("20000.00")

    def test_a_partial_credit_outside_the_ledger_is_detected(self, wallet):
        """Une fuite partielle est plus insidieuse qu'un solde entier non tracé."""
        _entry(wallet, "CREDIT", "500.00", "0.00", "500.00")
        Wallet.objects.filter(pk=wallet.pk).update(available_balance=Decimal("1500.00"))
        wallet.refresh_from_db()

        result = WalletReconciliationService.reconcile(wallet)

        assert not result.is_balanced
        assert result.closing_gap == Decimal("1000.00")

    def test_a_broken_chain_is_located_precisely(self, wallet):
        """Une écriture au calcul faux doit être désignée, pas seulement comptée."""
        _entry(wallet, "CREDIT", "500.00", "0.00", "500.00")
        broken = _entry(wallet, "CREDIT", "100.00", "999.00", "1099.00")
        Wallet.objects.filter(pk=wallet.pk).update(available_balance=Decimal("1099.00"))
        wallet.refresh_from_db()

        result = WalletReconciliationService.reconcile(wallet)

        assert not result.is_balanced
        assert len(result.breaks) == 1
        assert result.breaks[0].entry_id == broken.pk
        assert result.breaks[0].expected == Decimal("500.00")
        assert result.breaks[0].found == Decimal("999.00")

    def test_an_opening_balance_is_reported_apart_from_a_closing_gap(self, wallet):
        """Un portefeuille antérieur au grand livre et une fuite récente
        n'appellent pas la même action : on ne les confond pas."""
        _entry(wallet, "CREDIT", "100.00", "250.00", "350.00")
        Wallet.objects.filter(pk=wallet.pk).update(available_balance=Decimal("350.00"))
        wallet.refresh_from_db()

        result = WalletReconciliationService.reconcile(wallet)

        assert not result.is_balanced
        assert result.opening_gap == Decimal("250.00")
        assert result.closing_gap == Decimal("0.00")

    def test_a_debit_outside_the_ledger_is_detected_too(self, wallet):
        """Le contrôle doit être symétrique : de l'argent qui disparaît
        compte autant que de l'argent qui apparaît."""
        _entry(wallet, "CREDIT", "800.00", "0.00", "800.00")
        Wallet.objects.filter(pk=wallet.pk).update(available_balance=Decimal("300.00"))
        wallet.refresh_from_db()

        result = WalletReconciliationService.reconcile(wallet)

        assert not result.is_balanced
        assert result.closing_gap == Decimal("-500.00")


@pytest.mark.django_db
class TestFleetReconciliation:

    def test_unbalanced_isolates_only_the_faulty_wallets(self, wallet):
        other = _wallet_for("voisin")
        _entry(other, "CREDIT", "10.00", "0.00", "10.00")
        Wallet.objects.filter(pk=other.pk).update(available_balance=Decimal("10.00"))
        Wallet.objects.filter(pk=wallet.pk).update(available_balance=Decimal("777.00"))

        faulty = WalletReconciliationService.unbalanced()

        assert [r.wallet_id for r in faulty] == [wallet.pk]
        assert faulty[0].unexplained_amount == Decimal("777.00")
