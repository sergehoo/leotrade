"""
tests_phase/test_api_equity_curve.py
====================================

Série de valorisation et verdict de traçabilité.

Un graphique affirme plus fort qu'un nombre. Relier cinq points espacés
de six semaines produit une ligne continue, et cette ligne raconte une
trajectoire qui n'a jamais été mesurée. Le serveur rend donc un verdict
explicite, pour que deux clients ne tranchent pas différemment.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from portfolio.models import PortfolioSnapshot
from portfolio.services_equity_curve import MIN_POINTS_FOR_CURVE
from portfolio.services_onboarding import PaperOnboardingService

User = get_user_model()


@pytest.fixture(autouse=True)
def _reset_throttle_bucket():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="courbe", email="courbe@leotrade.test", password="StrongPass123!",
    )


@pytest.fixture
def client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def portfolio(db, user):
    return PaperOnboardingService.provision(user)


def _snapshots(portfolio, count: int, *, hours_apart: int = 24):
    now = timezone.now()
    for index in range(count):
        PortfolioSnapshot.objects.create(
            portfolio=portfolio,
            snapshot_time=now - timedelta(hours=hours_apart * (count - index)),
            equity=Decimal("10000.00") + Decimal(index * 10),
            balance=Decimal("10000.00"),
        )


def _curve(client, portfolio):
    return client.get(
        reverse("api-portfolios-equity-curve", kwargs={"pk": portfolio.pk})
    ).json()


@pytest.mark.django_db
class TestPlottabilityVerdict:

    def test_an_empty_series_is_not_plottable(self, client, portfolio):
        body = _curve(client, portfolio)

        assert body["point_count"] == 0
        assert body["is_plottable"] is False
        assert "TOO_FEW_POINTS" in body["not_plottable_reasons"]

    def test_a_series_below_the_threshold_is_refused(self, client, portfolio):
        """Deux points font un segment, pas une trajectoire."""
        _snapshots(portfolio, MIN_POINTS_FOR_CURVE - 1)

        body = _curve(client, portfolio)

        assert body["is_plottable"] is False
        assert body["not_plottable_reasons"] == ["TOO_FEW_POINTS"]
        assert body["minimum_points"] == MIN_POINTS_FOR_CURVE

    def test_a_dense_enough_series_is_plottable(self, client, portfolio):
        _snapshots(portfolio, MIN_POINTS_FOR_CURVE + 2)

        body = _curve(client, portfolio)

        assert body["is_plottable"] is True
        assert body["not_plottable_reasons"] == []

    def test_widely_spaced_points_are_refused_even_when_numerous(
        self, client, portfolio,
    ):
        """Le cas réellement présent en base : des instantanés espacés de
        semaines. Les relier inventerait tout l'intervalle."""
        _snapshots(portfolio, 10, hours_apart=24 * 14)

        body = _curve(client, portfolio)

        assert body["point_count"] == 10
        assert body["is_plottable"] is False
        assert "GAPS_TOO_WIDE" in body["not_plottable_reasons"]

    def test_the_verdict_comes_with_what_justifies_it(self, client, portfolio):
        """L'interface doit pouvoir expliquer le refus, pas seulement
        l'appliquer."""
        _snapshots(portfolio, 3)

        body = _curve(client, portfolio)

        assert body["point_count"] == 3
        assert body["median_gap_seconds"] is not None
        assert body["first_at"] is not None
        assert body["last_at"] is not None


@pytest.mark.django_db
class TestCurveContract:

    def test_points_are_oldest_first_for_charting(self, client, portfolio):
        _snapshots(portfolio, 6)

        points = _curve(client, portfolio)["points"]
        timestamps = [point["at"] for point in points]

        assert timestamps == sorted(timestamps)

    def test_amounts_travel_as_strings(self, client, portfolio):
        _snapshots(portfolio, 6)

        point = _curve(client, portfolio)["points"][0]

        for field in ("equity", "balance", "unrealized_pnl", "realized_pnl"):
            assert isinstance(point[field], str)

    def test_the_series_is_bounded(self, client, portfolio):
        """Une limite non bornée laisserait un client demander la table."""
        _snapshots(portfolio, 8)

        body = client.get(
            reverse("api-portfolios-equity-curve", kwargs={"pk": portfolio.pk}),
            {"limit": "999999"},
        ).json()

        assert body["point_count"] == 8

    def test_another_users_curve_is_invisible(self, client, db):
        intruder = User.objects.create_user(
            username="voisin", email="voisin@leotrade.test", password="StrongPass123!",
        )
        foreign = PaperOnboardingService.provision(intruder)

        response = client.get(
            reverse("api-portfolios-equity-curve", kwargs={"pk": foreign.pk})
        )

        assert response.status_code == 404


@pytest.mark.django_db
class TestScheduledCapture:

    def test_the_capture_task_feeds_every_active_portfolio(self, user, portfolio):
        """`PortfolioSnapshot` existait sans qu'aucune tâche ne l'alimente :
        la courbe ne se remplissait jamais."""
        from portfolio.tasks import capture_daily_snapshots_task

        before = PortfolioSnapshot.objects.filter(portfolio=portfolio).count()
        result = capture_daily_snapshots_task()

        assert result["captured"] >= 1
        assert PortfolioSnapshot.objects.filter(portfolio=portfolio).count() == before + 1

    def test_the_task_is_declared_in_the_beat_schedule(self):
        """Une tâche non planifiée ne s'exécute jamais : le défaut
        d'origine était l'absence d'entrée, pas l'absence de code."""
        from django.conf import settings

        tasks = {
            entry["task"] for entry in settings.CELERY_BEAT_SCHEDULE.values()
        }
        assert "portfolio.tasks.capture_daily_snapshots_task" in tasks

    def test_one_failing_portfolio_does_not_starve_the_others(
        self, user, portfolio, monkeypatch,
    ):
        from portfolio.models import Portfolio
        from portfolio.tasks import capture_daily_snapshots_task

        second = PaperOnboardingService.provision(user, name="Second")
        calls = {"n": 0}
        from portfolio.services import PortfolioService

        original = PortfolioService.create_snapshot

        def flaky(portfolio_arg):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("panne isolée")
            return original(portfolio_arg)

        monkeypatch.setattr(PortfolioService, "create_snapshot", staticmethod(flaky))

        result = capture_daily_snapshots_task()

        assert result["failed"] == 1
        assert result["captured"] == Portfolio.objects.filter(is_active=True).count() - 1
        assert second is not None
