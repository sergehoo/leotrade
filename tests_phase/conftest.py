"""
tests_phase/conftest.py
=======================

Configuration pytest partagée pour tous les tests de la suite tests_phase.

Lancement :
    cd <racine_projet>
    pytest tests_phase/ -p no:cacheprovider --django-settings-module=leoTrade.settings.test -v

Si tu n'as pas encore de settings.test, tu peux utiliser :
    DJANGO_SETTINGS_MODULE=leoTrade.settings.dev pytest tests_phase/ ...
"""

import pytest
from decimal import Decimal
from django.contrib.auth import get_user_model

# ── Helpers partagés ─────────────────────────────────────────────────────────

User = get_user_model()


@pytest.fixture
def user(db):
    """Utilisateur Django de base pour tous les tests."""
    return User.objects.create_user(
        username="testuser",
        email="test@leotrade.io",
        password="StrongPass123!",
    )


@pytest.fixture
def broker_paper(db, user):
    """BrokerAccount en mode PAPER (Deriv)."""
    from brokers.models import BrokerAccount
    return BrokerAccount.objects.create(
        user=user,
        broker="DERIV",
        name="Deriv PAPER",
        mode="PAPER",
        is_active=True,
        status="ACTIVE",
    )


@pytest.fixture
def broker_live(db, user):
    """BrokerAccount en mode LIVE (Deriv)."""
    from brokers.models import BrokerAccount
    return BrokerAccount.objects.create(
        user=user,
        broker="DERIV",
        name="Deriv LIVE",
        mode="LIVE",
        is_active=True,
        status="ACTIVE",
    )


@pytest.fixture
def portfolio_paper(db, user, broker_paper):
    """Portfolio branché sur un compte PAPER avec du cash disponible."""
    from portfolio.models import Portfolio
    return Portfolio.objects.create(
        user=user,
        broker_account=broker_paper,
        name="Paper Portfolio",
        starting_balance=Decimal("10000.00"),
        current_balance=Decimal("10000.00"),
        available_cash=Decimal("10000.00"),
        locked_cash=Decimal("0.00"),
        equity=Decimal("10000.00"),
        max_equity=Decimal("10000.00"),
        is_active=True,
        is_default=True,
    )


@pytest.fixture
def portfolio_live(db, user, broker_live):
    """Portfolio branché sur un compte LIVE avec du cash disponible."""
    from portfolio.models import Portfolio
    return Portfolio.objects.create(
        user=user,
        broker_account=broker_live,
        name="Live Portfolio",
        starting_balance=Decimal("10000.00"),
        current_balance=Decimal("10000.00"),
        available_cash=Decimal("10000.00"),
        locked_cash=Decimal("0.00"),
        equity=Decimal("10000.00"),
        max_equity=Decimal("10000.00"),
        is_active=True,
        is_default=False,
    )


@pytest.fixture
def risk_profile_paper(db, user, portfolio_paper):
    """Profil de risque permissif pour les tests PAPER."""
    from risk.models import RiskProfile
    return RiskProfile.objects.create(
        user=user,
        portfolio=portfolio_paper,
        name="Test Profile PAPER",
        is_active=True,
        is_default=True,
        max_risk_per_trade=Decimal("2.00"),
        max_daily_loss=Decimal("5.00"),
        max_weekly_loss=Decimal("10.00"),
        max_drawdown=Decimal("15.00"),
        max_open_positions=5,
        max_symbol_exposure_percent=Decimal("25.00"),
        max_asset_class_exposure_percent=Decimal("50.00"),
        max_correlated_exposure_percent=Decimal("40.00"),
        max_leverage=Decimal("3.00"),
        min_confidence=Decimal("0.60"),
        allow_short=True,
        allow_live_trading=True,
        require_stop_loss=False,
        kill_switch_enabled=True,
    )


@pytest.fixture
def risk_profile_live(db, user, portfolio_live):
    """Profil de risque permissif pour les tests LIVE."""
    from risk.models import RiskProfile
    return RiskProfile.objects.create(
        user=user,
        portfolio=portfolio_live,
        name="Test Profile LIVE",
        is_active=True,
        is_default=True,
        max_risk_per_trade=Decimal("2.00"),
        max_daily_loss=Decimal("5.00"),
        max_weekly_loss=Decimal("10.00"),
        max_drawdown=Decimal("15.00"),
        max_open_positions=5,
        max_symbol_exposure_percent=Decimal("25.00"),
        max_asset_class_exposure_percent=Decimal("50.00"),
        max_correlated_exposure_percent=Decimal("40.00"),
        max_leverage=Decimal("3.00"),
        min_confidence=Decimal("0.60"),
        allow_short=True,
        allow_live_trading=True,
        require_stop_loss=False,
        kill_switch_enabled=True,
    )
