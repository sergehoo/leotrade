"""
Dynamic stop-loss / take-profit management.

Implements:

- Trailing stop: SL is moved closer to current price as price moves
  favourably (never against), based either on a fixed percentage or an
  ATR multiple.
- Break-even shift: as soon as the trade reaches 1R profit, SL is moved
  to entry — the trade can no longer be a loser.
- Partial take-profit ladder: at 1R/2R/3R, mark portions of the position
  for partial close.

Every adjustment is computed but not auto-applied to the broker — the
caller decides when to send the modification (e.g. inside a Celery
task) so this module remains pure and unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


def _d(value, default="0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


@dataclass
class StopAdjustment:
    new_stop_loss: Optional[Decimal]
    new_take_profit: Optional[Decimal]
    move_to_break_even: bool
    partial_close_ratio: Decimal  # 0..1
    reason: str


class TrailingStopService:
    """
    Compute updated stop levels for a position.

    Args:
        entry_price: original entry price (cost basis).
        current_price: latest tick.
        side: "LONG" or "SHORT".
        stop_loss: current SL (unchanged if no move makes sense).
        take_profit: current TP.
        atr: ATR value (same units as price). If provided, trailing uses
            ``atr * atr_multiplier``; otherwise ``trail_percent`` is used.
        atr_multiplier: distance in ATR units (default 2.0).
        trail_percent: % trail when ATR not available (default 1.5%).
        break_even_after_r: enable break-even after this many R (1.0 = at 1R).
    """

    @staticmethod
    def compute(
        *,
        entry_price,
        current_price,
        side: str,
        stop_loss=None,
        take_profit=None,
        atr=None,
        atr_multiplier: Decimal = Decimal("2.0"),
        trail_percent: Decimal = Decimal("0.015"),
        break_even_after_r: Decimal = Decimal("1.0"),
    ) -> StopAdjustment:
        entry = _d(entry_price)
        price = _d(current_price)
        sl = _d(stop_loss) if stop_loss is not None else None
        tp = _d(take_profit) if take_profit is not None else None
        atr_dec = _d(atr) if atr is not None else None

        if entry <= 0 or price <= 0 or side not in ("LONG", "SHORT"):
            return StopAdjustment(sl, tp, False, Decimal("0"), "invalid_inputs")

        if atr_dec and atr_dec > 0:
            trail_distance = atr_dec * atr_multiplier
        else:
            trail_distance = price * trail_percent

        new_sl = sl
        move_be = False
        partial = Decimal("0")
        reasons: list[str] = []

        if side == "LONG":
            r_distance = entry - sl if sl else trail_distance
            if r_distance <= 0:
                r_distance = trail_distance

            r_multiple = (price - entry) / r_distance if r_distance else Decimal("0")

            candidate_sl = price - trail_distance
            if sl is None or candidate_sl > sl:
                new_sl = candidate_sl
                reasons.append("trailing_long")

            if r_multiple >= break_even_after_r and (sl is None or sl < entry):
                new_sl = max(new_sl or entry, entry)
                move_be = True
                reasons.append("break_even")

            if r_multiple >= 3:
                partial = Decimal("1.0")
                reasons.append("partial_3R")
            elif r_multiple >= 2:
                partial = Decimal("0.66")
                reasons.append("partial_2R")
            elif r_multiple >= 1:
                partial = Decimal("0.33")
                reasons.append("partial_1R")

        else:  # SHORT
            r_distance = sl - entry if sl else trail_distance
            if r_distance <= 0:
                r_distance = trail_distance

            r_multiple = (entry - price) / r_distance if r_distance else Decimal("0")

            candidate_sl = price + trail_distance
            if sl is None or candidate_sl < sl:
                new_sl = candidate_sl
                reasons.append("trailing_short")

            if r_multiple >= break_even_after_r and (sl is None or sl > entry):
                new_sl = min(new_sl or entry, entry)
                move_be = True
                reasons.append("break_even")

            if r_multiple >= 3:
                partial = Decimal("1.0")
                reasons.append("partial_3R")
            elif r_multiple >= 2:
                partial = Decimal("0.66")
                reasons.append("partial_2R")
            elif r_multiple >= 1:
                partial = Decimal("0.33")
                reasons.append("partial_1R")

        return StopAdjustment(
            new_stop_loss=new_sl,
            new_take_profit=tp,  # TP can stay; ladder handles partials
            move_to_break_even=move_be,
            partial_close_ratio=partial,
            reason=",".join(reasons) or "no_change",
        )
