"""
core/feature_flags.py
=====================

Kill switches simples lus à chaud depuis settings ou cache Redis.
"""

from __future__ import annotations

from django.conf import settings
from django.core.cache import cache


def is_trading_enabled() -> bool:
    """
    Trading global activé ? On vérifie d'abord Redis (toggle live admin),
    puis la valeur de settings.
    """
    # Toggle Redis prioritaire (set par l'admin sans redémarrage)
    cache_value = cache.get("feature:trading_enabled")
    if cache_value is not None:
        return bool(cache_value)
    return bool(getattr(settings, "FEATURE_TRADING_ENABLED", True))


def set_trading_enabled(enabled: bool) -> None:
    """
    Active/désactive le trading sans redémarrer l'app.
    Appelé depuis l'admin Django ou une commande de management.
    """
    cache.set("feature:trading_enabled", bool(enabled), timeout=None)


def require_trading_enabled():
    """
    Lève TradingDisabled si désactivé. À appeler dans les services critiques.
    """
    if not is_trading_enabled():
        from execution.orchestrator import TradingDisabled
        raise TradingDisabled("Trading globalement désactivé (kill switch)")
