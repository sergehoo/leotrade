"""
market/models_watchlist.py
==========================

Liste de suivi par utilisateur.

Volontairement minimale : un utilisateur, un instrument, un rang. La
liste de suivi est une préférence d'affichage, pas une donnée financière
— elle n'a ni à porter de prix, ni à dupliquer quoi que ce soit de
`Asset`.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from core.models import TimeStampedModel


class WatchlistItem(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="watchlist_items",
    )
    asset = models.ForeignKey(
        "market.Asset",
        on_delete=models.CASCADE,
        related_name="watchers",
    )
    #: Ordre choisi par l'utilisateur. Égalités départagées par la date
    #: d'ajout, pour que l'affichage reste stable d'un chargement à l'autre.
    position = models.PositiveIntegerField(default=0)
    note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        unique_together = [("user", "asset")]
        ordering = ["position", "created_at"]
        indexes = [
            models.Index(fields=["user", "position"]),
        ]

    def __str__(self):
        return f"{self.user} ★ {self.asset.symbol}"
