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


def live_block_reason(user) -> str:
    """Motif qui empêche l'exécution réelle, ou chaîne vide.

    Le mode LIVE n'est pas une préférence d'affichage : c'est une promesse
    que l'ordre partira chez le broker. Quand le KYC n'est pas approuvé,
    cette promesse est fausse — `AssistantRiskValidationService.check_kyc`
    et `BrokerAccountService.assert_live_allowed` bloqueront l'exécution.
    Annoncer « Mode réel » dans ces conditions induit l'utilisateur en
    erreur sur ce qui va se passer.
    """
    profile = getattr(user, "kyc_profile", None)
    if getattr(profile, "status", None) != "APPROVED":
        return "KYC_REQUIRED"
    return ""


def resolve_configured_trading_mode(user, session=None, default_portfolio=None) -> str:
    """Mode tel qu'il est CONFIGURÉ, sans tenir compte des blocages serveur.

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


def resolve_trading_mode(user, session=None, default_portfolio=None) -> str:
    """Mode de trading EFFECTIF : ce qui se produira réellement.

    Un blocage serveur rend le mode réel inatteignable. Annoncer « Mode
    réel » alors que `check_kyc` et `assert_live_allowed` refuseront
    l'exécution induit l'utilisateur en erreur sur la nature de ce qu'il
    s'apprête à faire — c'est précisément l'erreur qu'on ne peut pas se
    permettre sur une plateforme de trading.

    Le mode configuré reste exposé à part par `build_app_context`, pour
    que rien ne soit dissimulé.
    """
    if live_block_reason(user):
        return "PAPER"
    return resolve_configured_trading_mode(
        user, session=session, default_portfolio=default_portfolio,
    )


def build_app_context(user, session=None) -> dict:
    """Instantané complet du contexte, consommable par n'importe quel client."""
    portfolio = safe_default_portfolio(user)
    wallet = safe_wallet(user)
    configured = resolve_configured_trading_mode(
        user, session=session, default_portfolio=portfolio,
    )
    blocked_reason = live_block_reason(user)
    mode = "PAPER" if blocked_reason else configured

    return {
        "portfolio": portfolio,
        "wallet": wallet,
        # Ce qui se produira réellement.
        "trading_mode": mode,
        # Ce que l'utilisateur a demandé — exposé pour que l'interface
        # puisse expliquer l'écart au lieu de le masquer.
        "configured_trading_mode": configured,
        "live_blocked_reason": blocked_reason,
    }
