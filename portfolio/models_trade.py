"""
portfolio/models_trade.py
=========================

Modèle Trade : représente un round-trip CLOS (entrée + sortie).
C'est la SEULE source de vérité pour le PnL réalisé du portfolio.

Règle d'invariant :
    Portfolio.realized_pnl == Σ Trade.realized_pnl pour ce portfolio

Une Position peut générer plusieurs Trade en cas de fermeture partielle :
    Position OPEN qty=10 entry=100
       └── Trade #1 qty=4  exit=110 → realized=40
       └── Trade #2 qty=6  exit=120 → realized=120
"""

from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.utils import timezone


class Trade(models.Model):
    """
    Round-trip clos sur une Position.

    `realized_pnl` est immuable une fois inscrit. Toute correction passe
    par un nouveau Trade compensateur.
    """

    SIDE_CHOICES = [
        ("LONG", "Long"),
        ("SHORT", "Short"),
    ]

    portfolio = models.ForeignKey(
        "portfolio.Portfolio",
        on_delete=models.CASCADE,
        related_name="trades",
    )
    position = models.ForeignKey(
        "portfolio.Position",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trades",
    )

    # Pour traçabilité broker
    broker_account = models.ForeignKey(
        "brokers.BrokerAccount",
        on_delete=models.PROTECT,
        related_name="trades",
    )
    broker_fill_id = models.CharField(max_length=120, blank=True, null=True, db_index=True)
    closing_fill = models.ForeignKey(
        "execution.ExecutionFill",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="closes_trade",
    )
    opening_order = models.ForeignKey(
        "execution.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="opening_trades",
    )

    symbol = models.CharField(max_length=50, db_index=True)
    side = models.CharField(max_length=10, choices=SIDE_CHOICES)

    quantity = models.DecimalField(max_digits=24, decimal_places=8)
    entry_avg_price = models.DecimalField(max_digits=24, decimal_places=8)
    exit_avg_price = models.DecimalField(max_digits=24, decimal_places=8)

    gross_pnl = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    fees = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    realized_pnl = models.DecimalField(max_digits=18, decimal_places=2)

    # Récap cash de la position fermée (pour ledger)
    cash_invested = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    cash_returned = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    opened_at = models.DateTimeField(db_index=True)
    closed_at = models.DateTimeField(default=timezone.now, db_index=True)

    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-closed_at"]
        indexes = [
            models.Index(fields=["portfolio", "closed_at"]),
            models.Index(fields=["portfolio", "symbol"]),
            models.Index(fields=["broker_account"]),
        ]

    def __str__(self):
        return f"Trade {self.symbol} {self.side} qty={self.quantity} pnl={self.realized_pnl}"

    @property
    def hold_time_seconds(self) -> int:
        delta = (self.closed_at - self.opened_at)
        return int(delta.total_seconds())
