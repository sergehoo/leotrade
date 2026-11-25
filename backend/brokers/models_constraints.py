from __future__ import annotations

from decimal import Decimal
from django.db import models


class BrokerConstraint(models.Model):
    broker = models.CharField(max_length=20, db_index=True)
    symbol = models.CharField(max_length=50, db_index=True)

    min_qty = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0"))
    max_qty = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0"))
    qty_step = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0.00000001"))

    min_notional = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    price_tick = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0.00000001"))

    leverage_min = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("1"))
    leverage_max = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("1"))
    contract_size = models.DecimalField(max_digits=18, decimal_places=8, default=Decimal("1"))

    raw_payload = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("broker", "symbol")]
        ordering = ["broker", "symbol"]

    def __str__(self):
        return f"{self.broker} - {self.symbol}"