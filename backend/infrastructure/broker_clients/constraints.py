"""
OBSOLÈTE — ne pas utiliser.

`BrokerConstraintService` n'a aucun appelant dans le dépôt. Son
`normalize_quantity` ÉCRÊTE silencieusement au maximum broker au lieu de
refuser, ce qui donne l'illusion d'un garde-fou là où il n'y en a pas : le
chemin réellement exécuté est `core.precision.normalize_order`, qui, lui,
refuse (cf. `max_qty`).

Conservé le temps d'une suppression franche, mais toute nouvelle borne de
quantité va dans `core/precision.py`, pas ici.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_DOWN


def _d(value, default="0"):
    try:
        if value is None:
            return Decimal(default)
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


class BrokerConstraintService:
    @staticmethod
    def quantize_step(value: Decimal, step: Decimal) -> Decimal:
        value = _d(value)
        step = _d(step)
        if step <= 0:
            return value
        units = (value / step).quantize(Decimal("1"), rounding=ROUND_DOWN)
        return units * step

    @classmethod
    def normalize_quantity(cls, quantity: Decimal, min_qty: Decimal, max_qty: Decimal, qty_step: Decimal) -> Decimal:
        quantity = cls.quantize_step(quantity, qty_step)
        if quantity < min_qty:
            raise ValueError("Quantité inférieure au minimum broker.")
        if max_qty > 0 and quantity > max_qty:
            quantity = cls.quantize_step(max_qty, qty_step)
        return quantity

    @classmethod
    def normalize_price(cls, price: Decimal, price_tick: Decimal) -> Decimal:
        return cls.quantize_step(price, price_tick)

    @staticmethod
    def validate_notional(notional: Decimal, min_notional: Decimal):
        if _d(min_notional) > 0 and _d(notional) < _d(min_notional):
            raise ValueError("Notional inférieur au minimum broker.")