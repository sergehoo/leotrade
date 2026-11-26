"""
wallet/services_summary.py
==========================

Synthèse du portefeuille électronique.

Deux réserves coexistent et ne doivent jamais être confondues :

  - le **portefeuille électronique** (`Wallet`), qui contient de l'argent
    réel, alimenté par des fournisseurs de paiement ;
  - le **capital des portefeuilles de trading** (`Portfolio`), qui peut
    être entièrement simulé.

Les afficher côte à côte sans dire lequel est lequel conduit à croire
qu'on dispose d'une somme qu'on n'a pas — ou l'inverse, à hésiter à
engager de l'argent qui n'existe que dans une simulation.

La synthèse porte aussi l'état du rapprochement. Sur la base de
développement, un portefeuille présente 20 000 USD sans aucune écriture
de grand livre : l'anomalie doit être visible dans le produit, pas
seulement dans une commande d'administration.
"""

from __future__ import annotations

import logging
from decimal import Decimal

log = logging.getLogger("leotrade.wallet.summary")

ZERO = Decimal("0.00")


def _money(value) -> str:
    return str(Decimal(value or 0).quantize(Decimal("0.01")))


class WalletSummaryService:

    @staticmethod
    def build(user) -> dict:
        from portfolio.models import Portfolio
        from wallet.models import Wallet, WithdrawalRequest
        from wallet.services_reconciliation import WalletReconciliationService

        wallet = Wallet.objects.filter(user=user).first()
        if wallet is None:
            return WalletSummaryService._empty()

        reconciliation = WalletReconciliationService.reconcile(wallet)

        pending_withdrawals = WithdrawalRequest.objects.filter(
            wallet=wallet,
            status__in=["PENDING", "UNDER_REVIEW", "APPROVED"],
        )
        pending_amount = sum(
            (Decimal(row.amount or ZERO) for row in pending_withdrawals), ZERO,
        )

        # Capital des portefeuilles de trading, séparé selon qu'il engage
        # de l'argent réel ou non.
        simulated = ZERO
        live = ZERO
        for portfolio in Portfolio.objects.filter(user=user, is_active=True).select_related(
            "broker_account"
        ):
            broker = portfolio.broker_account
            is_simulated = (
                broker is None
                or broker.mode == "PAPER"
                or broker.broker == "SIMULATION"
            )
            equity = Decimal(portfolio.equity or ZERO)
            if is_simulated:
                simulated += equity
            else:
                live += equity

        return {
            "has_wallet": True,
            "currency": wallet.currency,
            "is_active": wallet.is_active,

            # ── Argent réel ────────────────────────────────────────────
            "available_balance": _money(wallet.available_balance),
            "locked_balance": _money(wallet.locked_balance),
            "total_balance": _money(wallet.total_balance),
            "total_deposited": _money(wallet.total_deposited),
            "total_withdrawn": _money(wallet.total_withdrawn),

            # ── Capital de trading, qualifié ───────────────────────────
            "simulated_trading_capital": _money(simulated),
            "live_trading_capital": _money(live),

            "pending_withdrawals_count": pending_withdrawals.count(),
            "pending_withdrawals_amount": _money(pending_amount),

            # ── Rapprochement ──────────────────────────────────────────
            # Exposé dans le produit : un solde que l'historique n'explique
            # pas est une information qui appartient à son propriétaire.
            "is_reconciled": reconciliation.is_balanced,
            "unexplained_amount": _money(reconciliation.unexplained_amount),
            "ledger_entry_count": reconciliation.entry_count,
            "ledger_break_count": len(reconciliation.breaks),
        }

    @staticmethod
    def _empty() -> dict:
        """Aucun portefeuille : on le dit, on n'invente pas de zéros."""
        return {
            "has_wallet": False,
            "currency": None,
            "is_active": False,
            "available_balance": None,
            "locked_balance": None,
            "total_balance": None,
            "total_deposited": None,
            "total_withdrawn": None,
            "simulated_trading_capital": None,
            "live_trading_capital": None,
            "pending_withdrawals_count": 0,
            "pending_withdrawals_amount": None,
            "is_reconciled": True,
            "unexplained_amount": None,
            "ledger_entry_count": 0,
            "ledger_break_count": 0,
        }
