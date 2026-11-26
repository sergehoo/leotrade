"""
tests_phase/test_api_portfolio_onboarding.py
============================================

Parcours d'accueil en simulation, et synthèse de portefeuille.

Un portefeuille exige un compte broker, et un compte broker exigeait
jusqu'ici un courtier réel. Un nouvel utilisateur arrivait donc sur un
tableau de bord vide dont la seule issue était d'ouvrir un compte chez
un tiers. Ces tests figent le chemin qui lève ce blocage, et les gardes
qui l'empêchent de devenir une porte dérobée vers l'argent réel.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework.test import APIClient

from brokers.models import BrokerAccount
from portfolio.models import CashLedgerEntry, Portfolio

User = get_user_model()


@pytest.fixture(autouse=True)
def _reset_throttle_bucket():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_user(db):
    return User.objects.create_user(
        username="novice", email="novice@leotrade.test", password="StrongPass123!",
    )


@pytest.fixture
def client(api_user):
    c = APIClient()
    c.force_authenticate(user=api_user)
    return c


def _provision(client, **payload):
    return client.post(
        reverse("api-portfolios-provision-paper"), payload, format="json",
    )


# ─────────────────────────────────────────────────────────────────────────────
#  1. Le parcours d'accueil
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestPaperProvisioning:

    def test_a_new_user_gets_a_usable_portfolio_in_one_call(self, client, api_user):
        response = _provision(client)

        assert response.status_code == 201, response.json()
        body = response.json()
        assert body["is_simulated"] is True
        assert body["trading_mode"] == "PAPER"

        portfolio = Portfolio.objects.get(pk=body["id"])
        assert portfolio.user_id == api_user.pk
        assert portfolio.is_default is True, "Le premier portefeuille doit être par défaut."

    def test_no_real_broker_account_is_required(self, client, api_user):
        _provision(client)

        broker = BrokerAccount.objects.get(user=api_user)
        assert broker.broker == "SIMULATION"
        assert broker.mode == "PAPER"
        # Aucun secret requis : rien à joindre.
        from brokers.services_accounts import BrokerAccountService

        assert BrokerAccountService.missing_secrets(broker) == []

    def test_the_capital_is_credited_exactly_once(self, client, api_user):
        """Régression : la première version écrivait le capital À LA FOIS sur
        `starting_balance` et comme écriture de grand livre. Or
        `recompute_cash_state` calcule `starting_balance + Σ(écritures)` :
        un portefeuille de 10 000 affichait 20 000.

        Vérifier l'existence d'une écriture ne suffisait pas — c'est le
        SOLDE RÉSULTANT qui devait être assert.
        """
        response = _provision(client, starting_balance="5000.00")

        portfolio = Portfolio.objects.get(pk=response.json()["id"])

        assert portfolio.starting_balance == Decimal("5000.00")
        assert portfolio.current_balance == Decimal("5000.00"), (
            "Le solde doit valoir le capital, pas son double."
        )
        assert portfolio.available_cash == Decimal("5000.00")
        assert portfolio.equity == Decimal("5000.00")

    def test_the_opening_capital_is_not_a_ledger_movement(self, client):
        """Le capital d'ouverture est la ligne de départ, pas une transaction :
        l'écrire dans le grand livre le ferait compter deux fois."""
        response = _provision(client, starting_balance="5000.00")

        portfolio = Portfolio.objects.get(pk=response.json()["id"])

        assert CashLedgerEntry.objects.filter(portfolio=portfolio).count() == 0

    def test_recomputing_does_not_inflate_the_balance(self, client):
        """Le recalcul doit être idempotent : l'appeler deux fois ne doit pas
        faire grossir le portefeuille."""
        from portfolio.services import PortfolioService

        response = _provision(client, starting_balance="5000.00")
        portfolio = Portfolio.objects.get(pk=response.json()["id"])

        PortfolioService.refresh_portfolio_metrics(portfolio)
        PortfolioService.refresh_portfolio_metrics(portfolio)
        portfolio.refresh_from_db()

        assert portfolio.current_balance == Decimal("5000.00")

    def test_a_second_portfolio_does_not_collide_on_the_name(self, client):
        first = _provision(client)
        second = _provision(client)

        assert first.status_code == 201
        assert second.status_code == 201, second.json()
        assert first.json()["name"] != second.json()["name"]

    def test_a_second_portfolio_does_not_steal_the_default_flag(self, client, api_user):
        first = _provision(client).json()
        _provision(client)

        assert Portfolio.objects.get(pk=first["id"]).is_default is True
        assert Portfolio.objects.filter(user=api_user, is_default=True).count() == 1

    def test_an_absurd_starting_capital_is_refused(self, client):
        too_low = _provision(client, starting_balance="1.00")
        too_high = _provision(client, starting_balance="99999999999.00")

        assert too_low.status_code == 400
        assert too_low.json()["code"] == "BALANCE_TOO_LOW"
        assert too_high.status_code == 400
        assert too_high.json()["code"] == "BALANCE_TOO_HIGH"

    def test_a_refused_provisioning_leaves_nothing_behind(self, client, api_user):
        """La transaction doit être atomique : un compte broker orphelin
        polluerait la liste des brokers sans portefeuille en face."""
        _provision(client, starting_balance="1.00")

        assert not Portfolio.objects.filter(user=api_user).exists()
        assert not BrokerAccount.objects.filter(user=api_user).exists()

    def test_provisioning_requires_authentication(self):
        anonymous = APIClient()

        assert _provision(anonymous).status_code in (401, 403)


# ─────────────────────────────────────────────────────────────────────────────
#  2. La simulation ne doit pas devenir une porte vers le réel
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestSimulationCannotGoLive:

    def test_the_model_refuses_a_live_simulation_account(self, api_user):
        account = BrokerAccount(
            user=api_user, name="Triche", broker="SIMULATION", mode="LIVE",
        )
        with pytest.raises(ValidationError) as excinfo:
            account.save()

        assert "mode" in excinfo.value.message_dict

    def test_the_api_refuses_to_create_one(self, client):
        response = client.post(
            reverse("api-brokers-list"),
            {"name": "Triche", "broker": "SIMULATION", "mode": "LIVE"},
            format="json",
        )

        assert response.status_code in (400, 403), response.json()

    def test_the_api_refuses_to_switch_an_existing_one(self, client, api_user):
        _provision(client)
        account = BrokerAccount.objects.get(user=api_user)

        response = client.patch(
            reverse("api-brokers-detail", kwargs={"pk": account.pk}),
            {"mode": "LIVE"}, format="json",
        )

        assert response.status_code in (400, 403)
        account.refresh_from_db()
        assert account.mode == "PAPER"

    def test_testing_the_connection_says_it_is_local(self, client, api_user):
        """Ni un faux succès réseau, ni une erreur : il n'y a rien à joindre,
        et la réponse doit le dire."""
        _provision(client)
        account = BrokerAccount.objects.get(user=api_user)

        response = client.post(
            reverse("api-brokers-test-connection", kwargs={"pk": account.pk})
        )

        assert response.status_code == 200
        assert response.json()["payload"]["venue"] == "local"


# ─────────────────────────────────────────────────────────────────────────────
#  3. Synthèse de portefeuille
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestPortfolioSummary:

    @pytest.fixture
    def portfolio(self, client):
        return Portfolio.objects.get(pk=_provision(client, starting_balance="10000.00").json()["id"])

    def _summary(self, client, portfolio):
        return client.get(
            reverse("api-portfolios-summary", kwargs={"pk": portfolio.pk})
        ).json()

    def test_a_fresh_portfolio_reports_zero_without_inventing_anything(self, client, portfolio):
        body = self._summary(client, portfolio)

        assert body["open_positions"] == 0
        assert body["total_pnl"] == "0.00"
        assert body["is_simulated"] is True
        assert body["base_currency"] == "USD"

    def test_amounts_travel_as_strings(self, client, portfolio):
        """Le backend calcule en Decimal ; un flottant en transit rouvrirait
        les erreurs d'arrondi que ce choix élimine."""
        body = self._summary(client, portfolio)

        for field in ("equity", "available_cash", "unrealized_pnl", "total_pnl"):
            assert isinstance(body[field], str), f"{field} doit transiter en chaîne."

    def test_pnl_is_measured_against_the_starting_capital(self, client, portfolio):
        """Rapporter un gain à l'équité courante, qui inclut déjà ce gain,
        sous-estimerait systématiquement la performance."""
        Portfolio.objects.filter(pk=portfolio.pk).update(
            realized_pnl=Decimal("1000.00"),
            equity=Decimal("11000.00"),
            starting_balance=Decimal("10000.00"),
        )

        body = self._summary(client, portfolio)

        assert body["total_pnl"] == "1000.00"
        assert body["total_pnl_percent"] == "10.00"

    def test_another_users_portfolio_is_invisible(self, client, db):
        intruder = User.objects.create_user(
            username="voisin", email="voisin@leotrade.test", password="StrongPass123!",
        )
        other = APIClient()
        other.force_authenticate(user=intruder)
        foreign = Portfolio.objects.get(pk=_provision(client).json()["id"])

        response = other.get(
            reverse("api-portfolios-summary", kwargs={"pk": foreign.pk})
        )

        assert response.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
#  4. Séparation simulation / réel sur les positions
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestPaperLiveSeparation:

    def test_positions_can_be_filtered_by_trading_mode(self, client, api_user):
        """Un tableau unique mélangeant simulé et réel est le genre d'écran
        sur lequel on clôture la mauvaise position."""
        _provision(client)

        response = client.get(reverse("api-positions-list"), {"trading_mode": "LIVE"})

        assert response.status_code == 200
        assert response.json()["count"] == 0

    def test_an_unknown_mode_filter_is_ignored_not_fatal(self, client):
        _provision(client)

        response = client.get(reverse("api-positions-list"), {"trading_mode": "n'importe"})

        assert response.status_code == 200
