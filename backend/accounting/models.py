"""
accounting/models.py
====================

Modèles transverses qui enjambent Wallet et Portfolio.

Transfer : représente un transfert atomique d'argent depuis le Wallet
plateforme d'un utilisateur vers un Portfolio de trading (ou inverse).
C'est l'opération en double-entrée canonique : un débit Wallet,
un crédit Portfolio, dans la même transaction.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models


class Transfer(models.Model):
    """
    Une opération double-entrée Wallet ↔ Portfolio.

    Idempotence : request_id unique. Tout retry avec le même request_id
    retourne le Transfer existant sans rejouer l'opération.
    """

    DIRECTION_CHOICES = [
        ("WALLET_TO_PORTFOLIO", "Wallet → Portfolio"),
        ("PORTFOLIO_TO_WALLET", "Portfolio → Wallet"),
    ]

    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("COMPLETED", "Completed"),
        ("FAILED", "Failed"),
        ("REVERTED", "Reverted"),
    ]

    request_id = models.CharField(
        max_length=120,
        unique=True,
        db_index=True,
        help_text="Idempotency key fournie par le caller (UUID).",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="accounting_transfers",
    )
    wallet = models.ForeignKey(
        "wallet.Wallet",
        on_delete=models.PROTECT,
        related_name="accounting_transfers",
    )
    portfolio = models.ForeignKey(
        "portfolio.Portfolio",
        on_delete=models.PROTECT,
        related_name="accounting_transfers",
    )

    direction = models.CharField(max_length=30, choices=DIRECTION_CHOICES)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=10, default="USD")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING", db_index=True)
    error_message = models.TextField(blank=True)

    # Liens vers les écritures effectives
    wallet_ledger_entry = models.ForeignKey(
        "wallet.WalletLedgerEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    portfolio_ledger_entry = models.ForeignKey(
        "portfolio.CashLedgerEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["wallet", "status"]),
            models.Index(fields=["portfolio", "status"]),
        ]

    def __str__(self):
        return f"Transfer {self.request_id} {self.amount} {self.currency} ({self.status})"

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "request_id": self.request_id,
            "direction": self.direction,
            "amount": str(self.amount),
            "currency": self.currency,
            "status": self.status,
            "wallet_id": self.wallet_id,
            "portfolio_id": self.portfolio_id,
        }
