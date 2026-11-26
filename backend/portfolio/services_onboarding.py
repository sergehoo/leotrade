"""
portfolio/services_onboarding.py
================================

Mise en service d'un portefeuille de simulation.

Rien ne fonctionne sans portefeuille, et un portefeuille exige un compte
broker. Un nouvel utilisateur se retrouvait donc devant un tableau de
bord vide avec, pour seule issue, l'ouverture d'un compte chez un
courtier — avant même d'avoir pu regarder la plateforme.

Ce service provisionne en un appel la chaîne complète : une place
d'exécution locale (`SIMULATION`, en mode PAPER), un portefeuille, et son
capital de départ.

Le capital est posé sur `starting_balance`, PAS écrit comme mouvement de
grand livre. C'est la convention du modèle, et elle n'est pas
optionnelle : `PortfolioService.recompute_cash_state` calcule
`current_balance = starting_balance + Σ(écritures)`. Faire les deux
double le solde — c'est exactement ce qui s'est produit à la première
version de ce service, un portefeuille de 10 000 affichant 20 000.

Le capital d'ouverture n'est donc pas une transaction : c'est la ligne de
départ à partir de laquelle les mouvements sont comptés, et c'est aussi
le dénominateur de la performance (`total_pnl_percent`). Sa traçabilité
est portée par `starting_balance` et `created_at`, pas par le grand
livre.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction

log = logging.getLogger("leotrade.portfolio.onboarding")

SIMULATION_BROKER = "SIMULATION"

DEFAULT_STARTING_BALANCE = Decimal("10000.00")
MIN_STARTING_BALANCE = Decimal("100.00")
# Plafond volontairement large : il ne protège pas d'un risque financier
# (cet argent n'existe pas) mais d'une saisie aberrante qui rendrait les
# pourcentages de risque illisibles.
MAX_STARTING_BALANCE = Decimal("10000000.00")


class OnboardingError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class PaperOnboardingService:

    @staticmethod
    def default_starting_balance() -> Decimal:
        return Decimal(
            str(getattr(settings, "PAPER_STARTING_BALANCE", DEFAULT_STARTING_BALANCE))
        )

    @classmethod
    def validate_starting_balance(cls, amount: Decimal) -> Decimal:
        if amount < MIN_STARTING_BALANCE:
            raise OnboardingError(
                "BALANCE_TOO_LOW",
                f"Le capital de départ doit être d'au moins {MIN_STARTING_BALANCE}.",
            )
        if amount > MAX_STARTING_BALANCE:
            raise OnboardingError(
                "BALANCE_TOO_HIGH",
                f"Le capital de départ ne peut pas dépasser {MAX_STARTING_BALANCE}.",
            )
        return amount

    @staticmethod
    def _unique_name(user, base: str) -> str:
        """Évite la collision sur `unique_together (user, name)`.

        Un utilisateur peut vouloir plusieurs portefeuilles de simulation
        (une stratégie par portefeuille) : on ne refuse pas, on suffixe.
        """
        from portfolio.models import Portfolio

        taken = set(
            Portfolio.objects.filter(user=user).values_list("name", flat=True)
        )
        if base not in taken:
            return base
        index = 2
        while f"{base} {index}" in taken:
            index += 1
        return f"{base} {index}"

    @classmethod
    @transaction.atomic
    def provision(
        cls,
        user,
        *,
        name: str | None = None,
        starting_balance: Decimal | None = None,
        currency: str = "USD",
    ):
        """Crée place locale + portefeuille + solde initial, en une transaction."""
        from brokers.models import BrokerAccount
        from portfolio.models import Portfolio
        from portfolio.services import PortfolioService

        amount = cls.validate_starting_balance(
            Decimal(starting_balance) if starting_balance is not None
            else cls.default_starting_balance()
        )

        broker_name = cls._unique_broker_name(user)
        broker = BrokerAccount.objects.create(
            user=user,
            name=broker_name,
            broker=SIMULATION_BROKER,
            mode="PAPER",
            is_active=True,
            status="ACTIVE",
            notes="Place d'exécution locale créée automatiquement.",
        )

        portfolio = Portfolio.objects.create(
            user=user,
            broker_account=broker,
            name=cls._unique_name(user, name or "Portefeuille de simulation"),
            base_currency=currency,
            is_active=True,
            # Premier portefeuille ⇒ par défaut, sinon l'utilisateur
            # resterait sans portefeuille par défaut et le contexte
            # n'aurait rien à présenter.
            is_default=not Portfolio.objects.filter(user=user, is_default=True).exists(),
        )

        # Capital d'ouverture : voir l'en-tête du module. Aucune écriture
        # de grand livre ici — `recompute_cash_state` l'ajoute déjà.
        portfolio.starting_balance = amount
        portfolio.max_equity = amount
        portfolio.save(update_fields=["starting_balance", "max_equity", "updated_at"])

        PortfolioService.refresh_portfolio_metrics(portfolio)

        # Profil de risque créé explicitement, pas paresseusement.
        # `RiskGuardService.get_default_profile` sait le fabriquer au premier
        # besoin, mais tant qu'aucune action ne l'a déclenché, l'utilisateur
        # ne voit aucune limite dans son interface — alors que la politique
        # de préservation s'applique déjà par défaut. Mieux vaut qu'il puisse
        # la lire et la régler dès l'arrivée.
        from risk.services import RiskGuardService

        RiskGuardService.get_default_profile(portfolio)

        portfolio.refresh_from_db()

        log.info(
            "portfolio.paper_provisioned user_id=%s portfolio_id=%s amount=%s %s",
            user.pk, portfolio.pk, amount, currency,
        )
        return portfolio

    @staticmethod
    def _unique_broker_name(user) -> str:
        from brokers.models import BrokerAccount

        base = "Simulation locale"
        taken = set(
            BrokerAccount.objects.filter(user=user).values_list("name", flat=True)
        )
        if base not in taken:
            return base
        index = 2
        while f"{base} {index}" in taken:
            index += 1
        return f"{base} {index}"
