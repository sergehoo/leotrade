"""
core/precision.py
-----------------

Outils de précision broker.

Sur Binance/MT5, les ordres rejetés pour cause de précision (LOT_SIZE,
PRICE_FILTER, MIN_NOTIONAL) sont une source majeure d'erreurs. Ce module
centralise l'arrondi correct vers le step inférieur (ROUND_DOWN) pour la
quantité et vers le tick (ROUND_HALF_UP) pour le prix.

Toutes les fonctions retournent des ``Decimal`` pour éviter les erreurs
d'imprécision flottante.

Usage typique
-------------

.. code-block:: python

    from core.precision import round_quantity, round_price, normalize_order

    qty = round_quantity(Decimal("0.123456"), step=Decimal("0.001"))   # 0.123
    px  = round_price(Decimal("42031.4567"), tick=Decimal("0.01"))     # 42031.46

    normalized = normalize_order(
        quantity=Decimal("0.123456"),
        price=Decimal("42031.4567"),
        constraint=broker_constraint,   # objet BrokerConstraint
    )
    # → dict avec quantity, price, notional, ok, reason
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, InvalidOperation
from typing import Any, Optional


_DEC_ZERO = Decimal("0")


def to_decimal(value, default: str = "0") -> Decimal:
    """Best-effort conversion to ``Decimal`` (never raises)."""
    try:
        if value is None or value == "":
            return Decimal(default)
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def round_quantity(quantity, step) -> Decimal:
    """
    Quantize ``quantity`` DOWN to the nearest multiple of ``step``.

    Why ROUND_DOWN: brokers reject orders that exceed available capital due
    to upward rounding, but never reject "smaller than requested". Always
    round down for sizing.
    """
    quantity = to_decimal(quantity)
    step = to_decimal(step)
    if step <= 0:
        return quantity
    if quantity <= 0:
        return _DEC_ZERO
    ratio = (quantity / step).quantize(Decimal("1"), rounding=ROUND_DOWN)
    return ratio * step


def round_price(price, tick) -> Decimal:
    """
    Quantize price to the nearest multiple of ``tick`` (HALF_UP).

    For limit orders: rounding to the nearest tick is fine because price
    deviation is symmetric around the requested price.
    """
    price = to_decimal(price)
    tick = to_decimal(tick)
    if tick <= 0:
        return price
    ratio = (price / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return ratio * tick


def quantity_to_str(quantity: Decimal, step: Decimal) -> str:
    """
    Format quantity as a fixed-precision string compatible with Binance.

    Binance /api/v3/order rejects "0E-8" or scientific notation. We format
    with the exact number of decimals needed by the step.
    """
    quantity = to_decimal(quantity)
    step = to_decimal(step)
    if step <= 0:
        return f"{quantity.normalize():f}"

    # Compute number of decimals from step (e.g. step=0.001 → 3 decimals)
    step_str = format(step.normalize(), "f")
    if "." in step_str:
        decimals = len(step_str.split(".")[1].rstrip("0"))
    else:
        decimals = 0

    quant = Decimal(10) ** -decimals if decimals > 0 else Decimal("1")
    return f"{quantity.quantize(quant, rounding=ROUND_DOWN):f}"


def price_to_str(price: Decimal, tick: Decimal) -> str:
    price = to_decimal(price)
    tick = to_decimal(tick)
    if tick <= 0:
        return f"{price.normalize():f}"

    tick_str = format(tick.normalize(), "f")
    if "." in tick_str:
        decimals = len(tick_str.split(".")[1].rstrip("0"))
    else:
        decimals = 0

    quant = Decimal(10) ** -decimals if decimals > 0 else Decimal("1")
    return f"{price.quantize(quant, rounding=ROUND_HALF_UP):f}"


@dataclass
class NormalizedOrder:
    quantity: Decimal
    price: Optional[Decimal]
    notional: Decimal
    ok: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "quantity": str(self.quantity),
            "price": str(self.price) if self.price is not None else None,
            "notional": str(self.notional),
            "ok": self.ok,
            "reason": self.reason,
        }


def normalize_order(
    *,
    quantity,
    price=None,
    constraint=None,
    min_qty: Optional[Decimal] = None,
    qty_step: Optional[Decimal] = None,
    price_tick: Optional[Decimal] = None,
    min_notional: Optional[Decimal] = None,
    max_qty: Optional[Decimal] = None,
) -> NormalizedOrder:
    """
    Normalize quantity/price against broker constraints.

    Either pass a ``constraint`` object (BrokerConstraint) or the explicit
    parameters ``min_qty/qty_step/price_tick/min_notional``.

    Returns a ``NormalizedOrder`` with ``ok=False`` and a reason if the order
    cannot satisfy the broker constraints.

    ``max_qty`` is the upper bound (0 or None = pas de borne). Il REFUSE au
    lieu d'écrêter : une quantité au-dessus du maximum broker signale une
    erreur de dimensionnement en amont, et l'écrêter silencieusement
    transformerait cette erreur en ordre valide de taille arbitraire —
    exactement ce qu'on veut éviter sur un chemin qui engage de l'argent.
    Il n'est volontairement PAS lu depuis ``constraint`` : les appelants qui
    ferment une position ne doivent pas hériter d'une borne qui pourrait
    bloquer une sortie.
    """
    if constraint is not None:
        min_qty = to_decimal(getattr(constraint, "min_qty", min_qty))
        qty_step = to_decimal(getattr(constraint, "qty_step", qty_step))
        price_tick = to_decimal(getattr(constraint, "price_tick", price_tick))
        min_notional = to_decimal(getattr(constraint, "min_notional", min_notional))
        # max_qty reste celui passé explicitement — cf. docstring.
    else:
        min_qty = to_decimal(min_qty)
        qty_step = to_decimal(qty_step)
        price_tick = to_decimal(price_tick) if price_tick is not None else _DEC_ZERO
        min_notional = to_decimal(min_notional)

    max_qty = to_decimal(max_qty) if max_qty is not None else _DEC_ZERO

    raw_qty = to_decimal(quantity)
    raw_price = to_decimal(price) if price is not None else None

    norm_qty = round_quantity(raw_qty, qty_step) if qty_step > 0 else raw_qty
    norm_price = (
        round_price(raw_price, price_tick) if (raw_price is not None and price_tick > 0) else raw_price
    )

    if norm_qty <= 0:
        return NormalizedOrder(
            quantity=_DEC_ZERO,
            price=norm_price,
            notional=_DEC_ZERO,
            ok=False,
            reason="Quantity rounded to 0 by qty_step.",
        )

    if min_qty > 0 and norm_qty < min_qty:
        return NormalizedOrder(
            quantity=norm_qty,
            price=norm_price,
            notional=_DEC_ZERO,
            ok=False,
            reason=f"Quantity {norm_qty} below broker min_qty {min_qty}.",
        )

    if max_qty > 0 and norm_qty > max_qty:
        return NormalizedOrder(
            quantity=norm_qty,
            price=norm_price,
            notional=_DEC_ZERO,
            ok=False,
            reason=(
                f"Quantity {norm_qty} above broker max_qty {max_qty}. "
                f"Un dépassement du maximum broker trahit une erreur de "
                f"dimensionnement en amont : l'ordre est refusé, pas écrêté."
            ),
        )

    notional = norm_qty * norm_price if norm_price is not None else _DEC_ZERO

    if min_notional > 0 and notional > 0 and notional < min_notional:
        return NormalizedOrder(
            quantity=norm_qty,
            price=norm_price,
            notional=notional,
            ok=False,
            reason=f"Notional {notional} below broker min_notional {min_notional}.",
        )

    return NormalizedOrder(
        quantity=norm_qty,
        price=norm_price,
        notional=notional,
        ok=True,
        reason="",
    )
