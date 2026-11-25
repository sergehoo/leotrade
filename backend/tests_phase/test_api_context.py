"""Contexte de démarrage exposé aux clients React / Flutter.

L'enjeu principal est le mode de trading : il doit être dérivé des comptes
broker et jamais d'une préférence client, sous peine de laisser un
utilisateur engager de l'argent réel en croyant simuler.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.urls import reverse

from brokers.models import BrokerAccount
from portfolio.models import Portfolio

User = get_user_model()
PASSWORD = "Correct-Horse-Battery-42"


@pytest.fixture(autouse=True)
def _reset_throttle_bucket():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user(db):
    user = User.objects.create_user(
        username="ctx", email="ctx@example.test", password=PASSWORD
    )
    EmailAddress.objects.create(
        user=user, email=user.email, verified=True, primary=True
    )
    return user


@pytest.fixture
def auth(client, user):
    tokens = client.post(
        reverse("api-auth-login"),
        {"email": user.email, "password": PASSWORD},
        content_type="application/json",
    ).json()
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens['access']}"}


def _broker(user, mode="PAPER", active=True, name="Compte"):
    return BrokerAccount.objects.create(
        user=user,
        name=name,
        broker="BINANCE",
        mode=mode,
        status="ACTIVE",
        is_active=active,
    )


def _portfolio(user, broker, default=True):
    return Portfolio.objects.create(
        user=user,
        broker_account=broker,
        name="Principal",
        base_currency="USD",
        starting_balance=Decimal("1000.00"),
        current_balance=Decimal("1000.00"),
        available_cash=Decimal("1000.00"),
        is_default=default,
        is_active=True,
    )


@pytest.mark.django_db
def test_context_requires_authentication(client):
    assert client.get(reverse("api-context")).status_code == 401


@pytest.mark.django_db
def test_context_without_portfolio_returns_null_not_zero(client, user, auth):
    """Sans portefeuille, le client reçoit null — jamais un solde à zéro.

    Un zéro se confondrait avec un compte réellement vide et mènerait à un
    écran trompeur au lieu d'un état vide explicite.
    """
    body = client.get(reverse("api-context"), **auth).json()
    assert body["portfolio"] is None
    assert body["trading_mode"] == "PAPER"


@pytest.mark.django_db
def test_context_mode_follows_the_default_portfolio_broker(client, user, auth):
    broker = _broker(user, mode="LIVE")
    _portfolio(user, broker)

    body = client.get(reverse("api-context"), **auth).json()
    assert body["trading_mode"] == "LIVE"
    assert body["portfolio"]["broker_account"]["mode"] == "LIVE"
    assert body["portfolio"]["base_currency"] == "USD"


@pytest.mark.django_db
def test_context_reports_live_when_any_active_broker_is_live(client, user, auth):
    """Sans portefeuille par défaut, un seul compte LIVE actif suffit."""
    _broker(user, mode="PAPER", name="Démo")
    _broker(user, mode="LIVE", name="Réel")

    body = client.get(reverse("api-context"), **auth).json()
    assert body["trading_mode"] == "LIVE"


@pytest.mark.django_db
def test_context_ignores_a_live_broker_that_is_inactive(client, user, auth):
    _broker(user, mode="PAPER", name="Démo")
    _broker(user, mode="LIVE", active=False, name="Réel désactivé")

    body = client.get(reverse("api-context"), **auth).json()
    assert body["trading_mode"] == "PAPER"


@pytest.mark.django_db
def test_context_mode_cannot_be_forced_by_the_client(client, user, auth):
    """Garantie de sécurité : le client ne choisit pas son mode.

    Même en poussant une préférence en session, la vérité reste celle du
    broker rattaché au portefeuille par défaut.
    """
    broker = _broker(user, mode="PAPER")
    _portfolio(user, broker)

    session = client.session
    session["trading_mode"] = "LIVE"
    session.save()

    body = client.get(reverse("api-context"), **auth).json()
    assert body["trading_mode"] == "PAPER"


@pytest.mark.django_db
def test_context_exposes_the_platform_kill_switch(client, user, auth, settings):
    from core.feature_flags import set_trading_enabled

    set_trading_enabled(False)
    body = client.get(reverse("api-context"), **auth).json()
    assert body["trading_enabled"] is False

    set_trading_enabled(True)
    body = client.get(reverse("api-context"), **auth).json()
    assert body["trading_enabled"] is True


@pytest.mark.django_db
def test_context_exposes_the_user_wallet(client, user, auth):
    # Le wallet est créé par signal à l'inscription.
    body = client.get(reverse("api-context"), **auth).json()
    assert body["wallet"] is not None
    assert "available_balance" in body["wallet"]


@pytest.mark.django_db
def test_context_never_leaks_broker_credentials(client, user, auth):
    broker = _broker(user, mode="LIVE")
    _portfolio(user, broker)

    raw = client.get(reverse("api-context"), **auth).content.decode()
    for forbidden in ("api_key", "api_secret", "deriv_token", "password"):
        assert forbidden not in raw, f"{forbidden} exposé dans /context/"
