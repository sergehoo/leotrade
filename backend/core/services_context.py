"""Contexte applicatif partagé.

Ce module porte l'état global dont **toutes** les interfaces ont besoin au
démarrage : portefeuille par défaut, solde du portefeuille électronique, mode
de trading effectif, kill switch de plateforme.

Pourquoi un service et non un context processor : la logique vivait dans
`core/context_processors.py`, donc uniquement accessible au rendu de template.
Les clients React et Flutter n'ont ni template ni session Django. La
dupliquer dans une vue d'API aurait créé deux vérités sur une question
sensible — « suis-je en PAPER ou en LIVE ? ». Le context processor délègue
désormais ici.
"""

from __future__ import annotations

from django.db.utils import OperationalError, ProgrammingError

from portfolio.models import Portfolio
from wallet.models import Wallet

TRADING_MODES = ("PAPER", "LIVE")


def safe_default_portfolio(user):
    """Portefeuille par défaut de l'utilisateur, ou None.

    Tolère une base dont le schéma n'est pas encore migré : la coquille de
    navigation doit s'afficher même pendant un déploiement.
    """
    if not user or not user.is_authenticated:
        return None
    try:
        return (
            Portfolio.objects.filter(user=user, is_default=True)
            .select_related("broker_account")
            .first()
        )
    except (ProgrammingError, OperationalError):
        return None


def safe_wallet(user):
    if not user or not user.is_authenticated:
        return None
    try:
        return Wallet.objects.filter(user=user).first()
    except (ProgrammingError, OperationalError):
        return None


def resolve_trading_mode(user, session=None, default_portfolio=None) -> str:
    """Mode de trading effectif.

    Priorité, du plus fiable au plus volatile :
      1. Mode du compte broker rattaché au portefeuille par défaut.
      2. Présence d'au moins un compte broker LIVE actif.
      3. Valeur en session (repli purement cosmétique, web uniquement).
      4. PAPER.

    L'ordre est délibéré : la vérité appartient au broker, jamais au client.
    Un client qui affiche LIVE pendant que le broker est en PAPER — ou
    l'inverse — conduit l'utilisateur à engager de l'argent réel en croyant
    simuler. Le mode n'est donc jamais lu depuis une préférence client.
    """
    if default_portfolio is None:
        default_portfolio = safe_default_portfolio(user)

    if default_portfolio is not None:
        broker_account = getattr(default_portfolio, "broker_account", None)
        mode = getattr(broker_account, "mode", None) if broker_account else None
        if mode in TRADING_MODES:
            return mode

    try:
        from brokers.models import BrokerAccount

        modes = list(
            BrokerAccount.objects.filter(user=user, is_active=True).values_list(
                "mode", flat=True
            )
        )
        if modes:
            # Un seul compte LIVE actif suffit à signaler que l'utilisateur
            # engage de l'argent réel quelque part.
            return "LIVE" if "LIVE" in modes else "PAPER"
    except (ProgrammingError, OperationalError):
        pass

    session_mode = session.get("trading_mode") if session else None
    if session_mode in TRADING_MODES:
        return session_mode

    return "PAPER"


def build_app_context(user, session=None) -> dict:
    """Instantané complet du contexte, consommable par n'importe quel client."""
    portfolio = safe_default_portfolio(user)
    wallet = safe_wallet(user)
    mode = resolve_trading_mode(user, session=session, default_portfolio=portfolio)
    return {
        "portfolio": portfolio,
        "wallet": wallet,
        "trading_mode": mode,
    }
