"""
tests_phase/test_api_wallet.py
==============================

Contrat du portefeuille électronique.

C'est le domaine qui touche à l'argent réel. Deux propriétés dominent :
aucune route ne doit déclencher de flux financier, et un solde que le
grand livre n'explique pas doit être visible — pas enfoui dans une
commande d'administration.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from wallet.models import Wallet, WalletLedgerEntry, WithdrawalRequest

User = get_user_model()


@pytest.fixture(autouse=True)
def _reset_throttle_bucket():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


def _make_user(username: str):
    return User.objects.create_user(
        username=username, email=f"{username}@leotrade.test", password="StrongPass123!",
    )


@pytest.fixture
def user(db):
    return _make_user("titulaire")


@pytest.fixture
def client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def wallet(db, user):
    wallet, _ = Wallet.objects.get_or_create(user=user, defaults={"currency": "USD"})
    return wallet


def _approve_kyc(user):
    from dashboard.models import KYCProfile

    profile, _ = KYCProfile.objects.update_or_create(
        user=user, defaults={"status": "APPROVED"},
    )
    return profile


def _fund(wallet, amount: str):
    """Crédite en passant par le grand livre, comme le ferait un dépôt."""
    from wallet.services_v2 import WalletLedgerService

    WalletLedgerService.credit(
        wallet_id=wallet.pk,
        amount=Decimal(amount),
        external_event_id=f"test-credit:{wallet.pk}:{amount}",
        description="Approvisionnement de test",
    )
    wallet.refresh_from_db()
    return wallet


# ─────────────────────────────────────────────────────────────────────────────
#  1. Aucune route ne déclenche de flux financier
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestNoFinancialFlowIsTriggered:

    def test_no_deposit_endpoint_is_exposed(self, client):
        """Un dépôt débite réellement l'instrument de paiement de
        l'utilisateur. L'ouvrir depuis l'API sans intégration validée
        reviendrait à activer un flux d'argent réel."""
        from django.urls import NoReverseMatch

        for name in ("api-wallet-deposit", "api-wallet-deposits-list"):
            with pytest.raises(NoReverseMatch):
                reverse(name)

    def test_a_withdrawal_request_moves_no_money(self, client, user, wallet):
        _approve_kyc(user)
        _fund(wallet, "500.00")

        response = client.post(
            reverse("api-wallet-withdrawals-list"),
            {"amount": "100.00", "destination_type": "BANK"},
            format="json",
        )

        assert response.status_code == 201, response.json()
        assert response.json()["status"] == "PENDING", (
            "Une demande doit attendre une revue, pas être payée."
        )

        wallet.refresh_from_db()
        # Les fonds sont VERROUILLÉS, pas sortis : le total est inchangé.
        assert wallet.available_balance == Decimal("400.00")
        assert wallet.locked_balance == Decimal("100.00")
        assert wallet.total_balance == Decimal("500.00")

    def test_a_withdrawal_request_is_written_to_the_ledger(self, client, user, wallet):
        """Un verrouillage sans écriture laisserait un solde inexpliqué —
        exactement ce que le rapprochement sert à détecter."""
        _approve_kyc(user)
        _fund(wallet, "500.00")
        before = WalletLedgerEntry.objects.filter(wallet=wallet).count()

        client.post(
            reverse("api-wallet-withdrawals-list"),
            {"amount": "100.00"}, format="json",
        )

        assert WalletLedgerEntry.objects.filter(wallet=wallet).count() == before + 1


# ─────────────────────────────────────────────────────────────────────────────
#  2. Gardes sur le retrait
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestWithdrawalGuards:

    def test_an_unapproved_kyc_blocks_the_request(self, client, user, wallet):
        """Sans cette garde, l'API deviendrait le chemin de contournement
        de la règle appliquée par les vues Django."""
        _fund(wallet, "500.00")

        response = client.post(
            reverse("api-wallet-withdrawals-list"), {"amount": "100.00"}, format="json",
        )

        assert response.status_code == 403
        assert response.json()["code"] == "KYC_REQUIRED"
        assert not WithdrawalRequest.objects.filter(wallet=wallet).exists()

    def test_an_insufficient_balance_is_refused(self, client, user, wallet):
        _approve_kyc(user)
        _fund(wallet, "50.00")

        response = client.post(
            reverse("api-wallet-withdrawals-list"), {"amount": "100.00"}, format="json",
        )

        assert response.status_code == 409
        assert response.json()["code"] == "INSUFFICIENT_FUNDS"

    def test_the_api_bounds_match_the_django_form(self, client, user, wallet):
        """Une API plus permissive que le formulaire serait le chemin
        qu'on emprunte pour contourner la limite."""
        _approve_kyc(user)
        _fund(wallet, "500000.00")

        too_small = client.post(
            reverse("api-wallet-withdrawals-list"), {"amount": "1.00"}, format="json",
        )
        too_large = client.post(
            reverse("api-wallet-withdrawals-list"), {"amount": "200000.00"}, format="json",
        )

        assert too_small.status_code == 400
        assert too_large.status_code == 400

    def test_a_full_account_number_is_refused(self, client, user, wallet):
        """Le champ sert à reconnaître une destination, pas à la définir :
        un numéro complet n'a rien à faire ici."""
        _approve_kyc(user)
        _fund(wallet, "500.00")

        response = client.post(
            reverse("api-wallet-withdrawals-list"),
            {"amount": "100.00", "destination_masked": "1234567890123456"},
            format="json",
        )

        assert response.status_code == 400
        assert "destination_masked" in response.json()

    def test_a_masked_destination_is_accepted(self, client, user, wallet):
        _approve_kyc(user)
        _fund(wallet, "500.00")

        response = client.post(
            reverse("api-wallet-withdrawals-list"),
            {"amount": "100.00", "destination_masked": "•••• 4242"},
            format="json",
        )

        assert response.status_code == 201

    def test_withdrawals_require_authentication(self):
        anonymous = APIClient()

        assert anonymous.post(
            reverse("api-wallet-withdrawals-list"), {"amount": "100.00"}, format="json",
        ).status_code in (401, 403)


# ─────────────────────────────────────────────────────────────────────────────
#  3. Synthèse : réel, simulé, et rapprochement
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestWalletSummary:

    def _summary(self, client):
        return client.get(reverse("api-wallet-summary")).json()

    def test_real_money_and_simulated_capital_are_named_apart(self, client, user, wallet):
        """Les confondre conduit à croire qu'on dispose d'une somme qu'on
        n'a pas — ou à hésiter à engager de l'argent qui n'existe que
        dans une simulation."""
        from portfolio.services_onboarding import PaperOnboardingService

        _fund(wallet, "300.00")
        PaperOnboardingService.provision(user, starting_balance=Decimal("10000.00"))

        body = self._summary(client)

        assert body["available_balance"] == "300.00"
        assert body["simulated_trading_capital"] == "10000.00"
        assert body["live_trading_capital"] == "0.00"

    def test_an_unexplained_balance_is_surfaced_to_its_owner(self, client, wallet):
        """Le cas réellement observé : 20 000 USD, aucune écriture.
        L'information appartient au propriétaire du solde."""
        Wallet.objects.filter(pk=wallet.pk).update(available_balance=Decimal("20000.00"))

        body = self._summary(client)

        assert body["is_reconciled"] is False
        assert body["unexplained_amount"] == "20000.00"
        assert body["ledger_entry_count"] == 0

    def test_a_consistent_wallet_reports_as_reconciled(self, client, wallet):
        _fund(wallet, "250.00")

        body = self._summary(client)

        assert body["is_reconciled"] is True
        assert body["unexplained_amount"] == "0.00"

    def test_locked_funds_are_reported_apart(self, client, user, wallet):
        _approve_kyc(user)
        _fund(wallet, "500.00")
        client.post(
            reverse("api-wallet-withdrawals-list"), {"amount": "120.00"}, format="json",
        )

        body = self._summary(client)

        assert body["locked_balance"] == "120.00"
        assert body["available_balance"] == "380.00"
        assert body["pending_withdrawals_count"] == 1
        assert body["pending_withdrawals_amount"] == "120.00"

    def test_amounts_travel_as_strings(self, client, wallet):
        _fund(wallet, "12.34")

        body = self._summary(client)

        for field in ("available_balance", "locked_balance", "total_balance"):
            assert isinstance(body[field], str)


# ─────────────────────────────────────────────────────────────────────────────
#  4. Cloisonnement
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestTenantIsolation:

    def test_another_users_ledger_is_invisible(self, client, wallet, db):
        intruder = _make_user("voisin")
        other_wallet, _ = Wallet.objects.get_or_create(
            user=intruder, defaults={"currency": "USD"},
        )
        _fund(other_wallet, "999.00")

        body = client.get(reverse("api-wallet-ledger-list")).json()

        assert body["count"] == 0

    def test_another_users_withdrawal_cannot_be_read(self, client, db):
        intruder = _make_user("voisin")
        other_wallet, _ = Wallet.objects.get_or_create(
            user=intruder, defaults={"currency": "USD"},
        )
        foreign = WithdrawalRequest.objects.create(
            wallet=other_wallet, amount=Decimal("10.00"), currency="USD",
        )

        response = client.get(
            reverse("api-wallet-withdrawals-detail", kwargs={"pk": foreign.pk})
        )

        assert response.status_code == 404
