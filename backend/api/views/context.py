"""Contexte de démarrage de l'application (React / Flutter).

Remplace les context processors Django, qui injectaient cet état dans chaque
rendu de template. Un client natif n'a ni template ni session : sans cet
endpoint, il devrait reconstituer le mode de trading à partir de la liste des
comptes broker — c'est-à-dire réimplémenter une règle de sécurité côté client.

Appelé une fois après l'authentification, puis rafraîchi quand un compte
broker ou le portefeuille par défaut change.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.feature_flags import is_trading_enabled
from core.services_context import build_app_context


class ContextBrokerSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    broker = serializers.CharField()
    mode = serializers.CharField()
    status = serializers.CharField()
    is_active = serializers.BooleanField()


class ContextPortfolioSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    base_currency = serializers.CharField()
    current_balance = serializers.DecimalField(max_digits=18, decimal_places=2)
    available_cash = serializers.DecimalField(max_digits=18, decimal_places=2)
    locked_cash = serializers.DecimalField(max_digits=18, decimal_places=2)
    is_active = serializers.BooleanField()
    broker_account = ContextBrokerSerializer(allow_null=True)


class ContextWalletSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    currency = serializers.CharField()
    available_balance = serializers.DecimalField(max_digits=18, decimal_places=2)
    locked_balance = serializers.DecimalField(max_digits=18, decimal_places=2)


class AppContextSerializer(serializers.Serializer):
    # Ce qui se produira réellement si un ordre est soumis.
    trading_mode = serializers.ChoiceField(choices=["PAPER", "LIVE"])
    # Ce que l'utilisateur a configuré sur ses comptes broker. Les deux
    # diffèrent quand un blocage serveur rend le mode réel inatteignable ;
    # l'interface doit alors expliquer l'écart, pas le masquer.
    configured_trading_mode = serializers.ChoiceField(choices=["PAPER", "LIVE"])
    live_blocked_reason = serializers.CharField(allow_blank=True)
    trading_enabled = serializers.BooleanField()
    portfolio = ContextPortfolioSerializer(allow_null=True)
    wallet = ContextWalletSerializer(allow_null=True)


class AppContextView(APIView):
    """GET /api/v1/context/"""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: AppContextSerializer},
        description=(
            "État global nécessaire au démarrage d'un client. `trading_mode` "
            "est le mode EFFECTIF : dérivé des comptes broker, jamais d'une "
            "préférence client, et ramené à PAPER quand un blocage serveur "
            "rend l'exécution réelle impossible. `configured_trading_mode` "
            "porte alors le mode demandé et `live_blocked_reason` son motif "
            "(KYC_REQUIRED), pour que l'interface explique l'écart. "
            "`trading_enabled` reflète le kill switch de plateforme : quand il "
            "est à false, aucune ouverture de position n'est acceptée, quel "
            "que soit l'utilisateur."
        ),
    )
    def get(self, request):
        context = build_app_context(request.user, session=getattr(request, "session", None))
        portfolio = context["portfolio"]
        wallet = context["wallet"]

        return Response(
            {
                "trading_mode": context["trading_mode"],
                "configured_trading_mode": context["configured_trading_mode"],
                "live_blocked_reason": context["live_blocked_reason"],
                # Kill switch global (core.feature_flags). L'exposer permet au
                # client d'afficher une bannière explicite et de désactiver les
                # boutons d'ordre — plutôt que de laisser l'utilisateur
                # découvrir le blocage au moment de valider.
                "trading_enabled": is_trading_enabled(),
                "portfolio": _portfolio_payload(portfolio),
                "wallet": _wallet_payload(wallet),
            }
        )


def _portfolio_payload(portfolio):
    """Aucune valeur inventée : sans portefeuille, le client reçoit null.

    Il affichera un état vide explicite (« créez un portefeuille ») plutôt
    qu'un solde à zéro, qui se confondrait avec un compte réellement vide.
    """
    if portfolio is None:
        return None
    broker = getattr(portfolio, "broker_account", None)
    return {
        "id": portfolio.id,
        "name": portfolio.name,
        "base_currency": portfolio.base_currency,
        "current_balance": portfolio.current_balance,
        "available_cash": portfolio.available_cash,
        "locked_cash": portfolio.locked_cash,
        "is_active": portfolio.is_active,
        "broker_account": (
            {
                "id": broker.id,
                "name": broker.name,
                "broker": broker.broker,
                "mode": broker.mode,
                "status": broker.status,
                "is_active": broker.is_active,
            }
            if broker
            else None
        ),
    }


def _wallet_payload(wallet):
    if wallet is None:
        return None
    return {
        "id": wallet.id,
        "currency": wallet.currency,
        "available_balance": wallet.available_balance,
        "locked_balance": wallet.locked_balance,
    }
