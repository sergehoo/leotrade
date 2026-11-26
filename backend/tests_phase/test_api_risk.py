"""
tests_phase/test_api_risk.py
============================

Contrat de l'API Risk Control.

Le profil de risque n'est pas une préférence d'affichage : c'est ce que
le moteur applique avant d'autoriser un ordre. Deux propriétés comptent
plus que le reste — personne ne doit pouvoir écrire le profil d'un autre,
et la politique Capital Preservation doit être visible et pilotable.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from portfolio.services_onboarding import PaperOnboardingService
from risk.models import RiskProfile

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
def owner(db):
    return _make_user("proprietaire")


@pytest.fixture
def intruder(db):
    return _make_user("intrus")


@pytest.fixture
def portfolio(db, owner):
    return PaperOnboardingService.provision(owner)


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


# ─────────────────────────────────────────────────────────────────────────────
#  1. Cloisonnement — la propriété la plus importante de ce domaine
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestTenantIsolation:

    def test_a_risk_profile_cannot_be_created_on_another_users_portfolio(
        self, intruder, portfolio, owner,
    ):
        """Faille réellement reproduite avant ce correctif : le serveur
        répondait 201. Le profil injecté arrivant avec `is_default=True`,
        il devenait celui que le moteur de risque applique — un tiers
        réécrivait donc les limites de sécurité de la victime.
        """
        response = _client(intruder).post(reverse("api-risk-profiles-list"), {
            "portfolio": portfolio.pk,
            "name": "Profil injecté",
            "max_risk_per_trade": "99.00",
            "max_daily_loss": "99.00",
        }, format="json")

        assert response.status_code == 400, response.json()
        assert "portfolio" in response.json()
        assert not RiskProfile.objects.filter(portfolio=portfolio).exclude(user=owner).exists()

    def test_the_error_does_not_reveal_that_the_portfolio_exists(
        self, intruder, portfolio,
    ):
        """Un identifiant appartenant à autrui et un identifiant inexistant
        doivent produire la même erreur : distinguer les deux révélerait
        quels portefeuilles existent."""
        client = _client(intruder)

        foreign = client.post(reverse("api-risk-profiles-list"), {
            "portfolio": portfolio.pk, "name": "A",
        }, format="json")
        missing = client.post(reverse("api-risk-profiles-list"), {
            "portfolio": 999999, "name": "B",
        }, format="json")

        import re

        def shape(response):
            # L'identifiant soumis figure dans le message : l'attaquant le
            # connaît déjà, il ne révèle rien. C'est la FORME de l'erreur
            # qui ne doit pas distinguer les deux cas.
            return [re.sub(r"\d+", "N", str(item)) for item in response.json()["portfolio"]]

        assert foreign.status_code == missing.status_code == 400
        assert shape(foreign) == shape(missing)

    def test_an_allocation_cannot_target_another_users_portfolio(
        self, intruder, portfolio,
    ):
        response = _client(intruder).post(reverse("api-allocations-list"), {
            "portfolio": portfolio.pk, "target_weight": "50.00",
        }, format="json")

        assert response.status_code == 400
        assert "portfolio" in response.json()

    def test_a_profile_can_be_created_on_ones_own_portfolio(self, owner, portfolio):
        response = _client(owner).post(reverse("api-risk-profiles-list"), {
            "portfolio": portfolio.pk,
            "name": "Mon profil",
        }, format="json")

        assert response.status_code == 201, response.json()
        assert RiskProfile.objects.get(pk=response.json()["id"]).user_id == owner.pk

    def test_another_users_profile_is_invisible(self, owner, intruder, portfolio):
        profile = RiskProfile.objects.create(
            user=owner, portfolio=portfolio, name="Privé",
        )

        listing = _client(intruder).get(reverse("api-risk-profiles-list")).json()
        detail = _client(intruder).get(
            reverse("api-risk-profiles-detail", kwargs={"pk": profile.pk})
        )

        assert listing["count"] == 0
        assert detail.status_code == 404

    def test_a_profile_cannot_be_moved_to_another_users_portfolio(
        self, owner, intruder, portfolio,
    ):
        """Le contournement par mise à jour : créer chez soi, puis déplacer."""
        intruder_portfolio = PaperOnboardingService.provision(intruder)
        profile = RiskProfile.objects.create(
            user=intruder, portfolio=intruder_portfolio, name="Mobile",
        )

        response = _client(intruder).patch(
            reverse("api-risk-profiles-detail", kwargs={"pk": profile.pk}),
            {"portfolio": portfolio.pk}, format="json",
        )

        assert response.status_code == 400
        profile.refresh_from_db()
        assert profile.portfolio_id == intruder_portfolio.pk


# ─────────────────────────────────────────────────────────────────────────────
#  2. Capital Preservation : visible et pilotable
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestCapitalPreservationExposure:

    def test_the_preservation_flags_are_part_of_the_contract(self, owner, portfolio):
        """Absents du contrat, ils rendaient la principale protection du
        capital invisible et non modifiable depuis les clients."""
        profile = RiskProfile.objects.create(
            user=owner, portfolio=portfolio, name="Prudent",
        )

        body = _client(owner).get(
            reverse("api-risk-profiles-detail", kwargs={"pk": profile.pk})
        ).json()

        for field in (
            "preservation_mode",
            "allow_volatile_instruments",
            "allow_speculative_instruments",
            "max_monthly_loss",
        ):
            assert field in body, f"« {field} » doit figurer au contrat."

    def test_preservation_is_enabled_by_default(self, owner, portfolio):
        response = _client(owner).post(reverse("api-risk-profiles-list"), {
            "portfolio": portfolio.pk, "name": "Neuf",
        }, format="json")

        assert response.json()["preservation_mode"] is True
        assert response.json()["allow_speculative_instruments"] is False

    def test_opting_into_speculative_instruments_is_explicit(self, owner, portfolio):
        """L'opt-in doit être possible — mais demandé, jamais implicite."""
        created = _client(owner).post(reverse("api-risk-profiles-list"), {
            "portfolio": portfolio.pk,
            "name": "Agressif",
            "preservation_mode": False,
            "allow_speculative_instruments": True,
        }, format="json")

        assert created.status_code == 201
        profile = RiskProfile.objects.get(pk=created.json()["id"])
        assert profile.preservation_mode is False
        assert profile.allow_speculative_instruments is True


# ─────────────────────────────────────────────────────────────────────────────
#  3. Profil par défaut
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestDefaultProfile:

    def test_set_default_promotes_exactly_one_profile(self, owner, portfolio):
        first = RiskProfile.objects.create(
            user=owner, portfolio=portfolio, name="A", is_default=True,
        )
        second = RiskProfile.objects.create(
            user=owner, portfolio=portfolio, name="B", is_default=False,
        )

        response = _client(owner).post(
            reverse("api-risk-profiles-set-default", kwargs={"pk": second.pk})
        )

        assert response.status_code == 200
        first.refresh_from_db()
        second.refresh_from_db()
        assert second.is_default is True
        assert first.is_default is False

    def test_another_users_profile_cannot_be_promoted(self, owner, intruder, portfolio):
        profile = RiskProfile.objects.create(
            user=owner, portfolio=portfolio, name="Privé",
        )

        response = _client(intruder).post(
            reverse("api-risk-profiles-set-default", kwargs={"pk": profile.pk})
        )

        assert response.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
#  4. États de risque et kill switch
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestRiskStates:

    def test_refreshing_states_requires_owning_the_portfolio(self, intruder, portfolio):
        response = _client(intruder).post(
            reverse("api-risk-utils-refresh-states"),
            {"portfolio_id": portfolio.pk}, format="json",
        )

        assert response.status_code == 404

    def test_refreshing_states_returns_the_measured_losses(self, owner, portfolio):
        response = _client(owner).post(
            reverse("api-risk-utils-refresh-states"),
            {"portfolio_id": portfolio.pk}, format="json",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["daily_loss_percent"] == "0.0000"
        assert "weekly_loss_percent" in body

    def test_resolving_a_kill_switch_requires_owning_the_portfolio(
        self, intruder, portfolio,
    ):
        """Lever un kill switch rouvre l'exécution : c'est une action de
        sûreté, elle ne doit jamais traverser la frontière du compte."""
        response = _client(intruder).post(
            reverse("api-kill-switch-events-resolve-for-portfolio"),
            {"portfolio_id": portfolio.pk}, format="json",
        )

        assert response.status_code == 404

    def test_states_are_scoped_to_the_caller(self, owner, intruder, portfolio):
        _client(owner).post(
            reverse("api-risk-utils-refresh-states"),
            {"portfolio_id": portfolio.pk}, format="json",
        )

        assert _client(intruder).get(reverse("api-daily-risk-states-list")).json()["count"] == 0
        assert _client(owner).get(reverse("api-daily-risk-states-list")).json()["count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
#  5. Synthèse consolidée
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestRiskSummary:

    def _summary(self, user, portfolio):
        return _client(user).get(
            reverse("api-risk-utils-summary", kwargs={"portfolio_id": portfolio.pk})
        )

    def test_it_reports_limit_usage_not_just_the_limits(self, owner, portfolio):
        """Connaître la limite n'apprend rien : c'est la part consommée qui
        change la décision."""
        body = self._summary(owner, portfolio).json()

        keys = {row["key"] for row in body["limits"]}
        assert keys == {"daily_loss", "weekly_loss", "drawdown"}
        for row in body["limits"]:
            assert "usage_percent" in row
            assert "consumed_percent" in row
            assert "limit_percent" in row

    def test_usage_is_null_when_no_limit_is_set(self, owner, portfolio):
        """Afficher « 0 % utilisé » sans limite laisserait croire à une
        protection qui n'existe pas."""
        profile = RiskProfile.objects.get(portfolio=portfolio)
        profile.max_daily_loss = Decimal("0")
        profile.save(update_fields=["max_daily_loss"])

        body = self._summary(owner, portfolio).json()
        daily = next(r for r in body["limits"] if r["key"] == "daily_loss")

        assert daily["usage_percent"] is None

    def test_usage_is_computed_against_the_profile_limit(self, owner, portfolio):
        from risk.models import DailyRiskState
        from django.utils import timezone

        profile = RiskProfile.objects.get(portfolio=portfolio)
        profile.max_daily_loss = Decimal("4.00")
        profile.save(update_fields=["max_daily_loss"])
        DailyRiskState.objects.create(
            portfolio=portfolio, day=timezone.now().date(),
            total_loss_percent=Decimal("3.00"),
        )

        body = self._summary(owner, portfolio).json()
        daily = next(r for r in body["limits"] if r["key"] == "daily_loss")

        assert daily["consumed_percent"] == "3.00"
        assert daily["limit_percent"] == "4.00"
        assert daily["usage_percent"] == "75.00"

    def test_an_active_kill_switch_is_surfaced_with_its_reason(self, owner, portfolio):
        """Un kill switch actif interdit toute ouverture : c'est
        l'information la plus importante de cet écran."""
        from risk.models import KillSwitchEvent

        profile = RiskProfile.objects.get(portfolio=portfolio)
        KillSwitchEvent.objects.create(
            portfolio=portfolio, risk_profile=profile,
            reason_code="DAILY_LOSS_LIMIT",
            reason="Limite de perte journalière atteinte.",
            is_active=True,
        )

        body = self._summary(owner, portfolio).json()

        assert body["kill_switch_active"] is True
        assert body["kill_switch_reason_code"] == "DAILY_LOSS_LIMIT"
        assert "journalière" in body["kill_switch_reason"]

    def test_the_preservation_policy_is_part_of_the_summary(self, owner, portfolio):
        body = self._summary(owner, portfolio).json()

        assert body["profile"]["preservation_mode"] is True
        assert body["profile"]["allow_speculative_instruments"] is False

    def test_another_users_portfolio_is_indistinguishable_from_a_missing_one(
        self, intruder, portfolio,
    ):
        foreign = self._summary(intruder, portfolio)
        missing = _client(intruder).get(
            reverse("api-risk-utils-summary", kwargs={"portfolio_id": 999999})
        )

        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json()
