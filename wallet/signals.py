import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Wallet, WalletTransaction

User = get_user_model()
log = logging.getLogger("lyneci.wallet.signals")


@receiver(post_save, sender=User)
def create_user_wallet(sender, instance, created, **kwargs):
    if created:
        Wallet.objects.get_or_create(
            user=instance,
            defaults={"currency": settings.WALLET_DEFAULT_CURRENCY},
        )


@receiver(post_save, sender=WalletTransaction)
def sync_wallet_transaction_to_portfolio(sender, instance, **kwargs):
    """
    Pont Wallet → Portfolio.

    Quand une WalletTransaction de type DEPOSIT ou WITHDRAWAL passe à SUCCEEDED,
    on reflète le mouvement de cash sur le Portfolio par défaut de l'utilisateur
    via une CashLedgerEntry.

    Idempotence : on vérifie qu'aucune CashLedgerEntry avec
    reference_type="WALLET_TRANSACTION" et reference_id=str(instance.id)
    n'existe déjà avant d'en créer une.

    Pourquoi ici et pas dans WalletService ?
    Le service est appelé depuis plusieurs chemins (webhook provider, admin, tâche
    Celery) ; un signal post_save garantit que quel que soit le chemin de
    mise à jour, le ledger portfolio est toujours synchronisé.
    """
    if instance.status != "SUCCEEDED":
        return

    if instance.tx_type not in ("DEPOSIT", "WITHDRAWAL"):
        return

    try:
        from portfolio.models import CashLedgerEntry, Portfolio
        from portfolio.services import PortfolioAccountingService, PortfolioService

        # Idempotence : ne créer l'entrée qu'une seule fois
        already_applied = CashLedgerEntry.objects.filter(
            reference_type="WALLET_TRANSACTION",
            reference_id=str(instance.id),
        ).exists()
        if already_applied:
            return

        portfolio = (
            Portfolio.objects
            .filter(user=instance.wallet.user, is_active=True)
            .order_by("-is_default", "-created_at")
            .first()
        )
        if not portfolio:
            log.warning(
                "sync_wallet_transaction_to_portfolio: aucun portfolio actif "
                "pour user_id=%s wallet_tx_id=%s",
                instance.wallet.user_id,
                instance.id,
            )
            return

        entry_type = "DEPOSIT" if instance.tx_type == "DEPOSIT" else "WITHDRAWAL"
        # Les retraits sont des montants négatifs dans le ledger
        ledger_amount = instance.amount if instance.tx_type == "DEPOSIT" else -instance.amount

        PortfolioAccountingService.add_ledger_entry(
            portfolio=portfolio,
            entry_type=entry_type,
            amount=ledger_amount,
            currency=instance.currency,
            reference_type="WALLET_TRANSACTION",
            reference_id=str(instance.id),
            description=(
                f"Dépôt via wallet #{instance.id}"
                if instance.tx_type == "DEPOSIT"
                else f"Retrait via wallet #{instance.id}"
            ),
            metadata={
                "wallet_transaction_id": str(instance.id),
                "source": "wallet_bridge",
                "provider": getattr(instance, "provider", "") or "",
            },
        )

        PortfolioService.recompute_cash_state(portfolio)

        log.info(
            "wallet_bridge.applied tx_id=%s tx_type=%s amount=%s portfolio_id=%s",
            instance.id,
            instance.tx_type,
            instance.amount,
            portfolio.id,
        )

    except Exception:
        log.exception(
            "wallet_bridge.failed wallet_tx_id=%s tx_type=%s amount=%s",
            instance.id,
            getattr(instance, "tx_type", "?"),
            getattr(instance, "amount", "?"),
        )
