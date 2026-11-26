"""
wallet/services_reconciliation.py
=================================

Rapprochement entre le solde d'un portefeuille et son grand livre.

`WalletLedgerService` pose une règle d'or : aucune ligne de code en dehors
de lui et de `accounting.TransferService` ne doit modifier
`available_balance` ou `locked_balance`. Rien ne vérifiait cette règle.
Un solde posé directement sur le champ — par le shell, l'admin, une
fixture, ou un service qui court-circuite le grand livre — restait
indétectable.

Le contrôle ne recalcule pas le solde à partir des montants, ce qui
supposerait de réinterpréter le signe de chaque type d'écriture. Il
vérifie la CHAÎNE que le service écrit déjà : le `balance_after` d'une
écriture doit être le `balance_before` de la suivante, et la dernière
doit coïncider avec le solde courant. C'est l'invariant le plus proche
de ce que le grand livre prétend être, et il attrape aussi bien un solde
écrit hors grand livre qu'une écriture au calcul faux.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal

from .models import Wallet, WalletLedgerEntry

log = logging.getLogger("leotrade.wallet.reconciliation")

ZERO = Decimal("0.00")


@dataclass
class LedgerBreak:
    """Une rupture de chaîne, localisée."""

    entry_id: int | None
    position: int
    expected: Decimal
    found: Decimal
    detail: str

    @property
    def gap(self) -> Decimal:
        return self.found - self.expected


@dataclass
class ReconciliationResult:
    wallet_id: int
    currency: str
    available_balance: Decimal
    locked_balance: Decimal
    entry_count: int
    ledger_total: Decimal
    opening_gap: Decimal
    breaks: list[LedgerBreak] = field(default_factory=list)

    @property
    def balance_total(self) -> Decimal:
        return self.available_balance + self.locked_balance

    @property
    def closing_gap(self) -> Decimal:
        """Écart entre le solde réel et ce que le grand livre explique."""
        return self.balance_total - self.ledger_total

    @property
    def is_balanced(self) -> bool:
        return not self.breaks and self.closing_gap == ZERO and self.opening_gap == ZERO

    @property
    def unexplained_amount(self) -> Decimal:
        """Montant que le grand livre n'explique pas, ouverture comprise."""
        return self.opening_gap + self.closing_gap

    def summary(self) -> str:
        if self.is_balanced:
            return (
                f"portefeuille {self.wallet_id} : équilibré "
                f"({self.entry_count} écriture(s), {self.balance_total} {self.currency})"
            )
        parts = [f"portefeuille {self.wallet_id} : DÉSÉQUILIBRÉ"]
        if self.opening_gap:
            parts.append(f"ouverture non justifiée {self.opening_gap} {self.currency}")
        if self.closing_gap:
            parts.append(f"clôture non justifiée {self.closing_gap} {self.currency}")
        if self.breaks:
            parts.append(f"{len(self.breaks)} rupture(s) de chaîne")
        parts.append(f"solde {self.balance_total} {self.currency}, {self.entry_count} écriture(s)")
        return " — ".join(parts)


class WalletReconciliationService:

    @staticmethod
    def reconcile(wallet: Wallet) -> ReconciliationResult:
        entries = list(
            WalletLedgerEntry.objects
            .filter(wallet=wallet)
            .order_by("created_at", "id")
            .only("id", "entry_type", "balance_before", "balance_after")
        )

        available = Decimal(wallet.available_balance or ZERO)
        locked = Decimal(wallet.locked_balance or ZERO)

        # Un portefeuille créé avant l'existence du grand livre peut ouvrir
        # sur un solde non nul. On le rapporte au lieu de le dissimuler dans
        # l'écart de clôture : les deux causes n'appellent pas la même action.
        opening_gap = (
            Decimal(entries[0].balance_before) if entries else ZERO
        )

        breaks: list[LedgerBreak] = []
        running = opening_gap

        for position, entry in enumerate(entries):
            before = Decimal(entry.balance_before)
            if before != running:
                breaks.append(LedgerBreak(
                    entry_id=entry.id,
                    position=position,
                    expected=running,
                    found=before,
                    detail=(
                        f"l'écriture {entry.entry_type} ouvre à {before} alors que "
                        f"la précédente ferme à {running}"
                    ),
                ))
            running = Decimal(entry.balance_after)

        result = ReconciliationResult(
            wallet_id=wallet.pk,
            currency=wallet.currency,
            available_balance=available,
            locked_balance=locked,
            entry_count=len(entries),
            ledger_total=running,
            opening_gap=opening_gap,
            breaks=breaks,
        )

        if not result.is_balanced:
            log.warning(
                "wallet.reconciliation_failed wallet_id=%s unexplained=%s currency=%s breaks=%s",
                wallet.pk, result.unexplained_amount, wallet.currency, len(breaks),
            )
        return result

    @classmethod
    def reconcile_all(cls, queryset=None) -> list[ReconciliationResult]:
        qs = queryset if queryset is not None else Wallet.objects.all()
        return [cls.reconcile(wallet) for wallet in qs.order_by("pk")]

    @classmethod
    def unbalanced(cls, queryset=None) -> list[ReconciliationResult]:
        return [r for r in cls.reconcile_all(queryset) if not r.is_balanced]
