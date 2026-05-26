"""
Feedback loop — learn from past trades.

The legacy AI engine emitted scores without ever looking back: a strategy
that lost money still got the same confidence on the next run. This
module computes a per-strategy multiplier ∈ [0.5, 1.5] derived from
recent realized PnL and win rate, applied to ``OpportunityScore.confidence``.

Why bound it
------------

We deliberately keep the multiplier bounded so a single losing streak
can't fully veto a strategy nor a hot streak can't override risk caps.
That preserves the principle that the risk engine — not the scorer —
remains the source of truth for what gets executed.

Inputs
------

We read recent ``Order`` rows for a given strategy/portfolio and compute:

- win rate (filled & PnL>0) over the last ``window`` orders
- average R-multiple (PnL / risked amount)
- Sharpe-like ratio (mean / std of per-order returns)

Then we collapse them into a single multiplier using a logistic blend.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class StrategyFeedback:
    win_rate: float          # 0..1
    average_r: float         # average risk multiple realized
    sharpe_like: float       # mean/std of per-trade returns
    sample_size: int
    multiplier: float        # 0.5..1.5
    payload: dict


def _logistic(x: float, k: float = 4.0) -> float:
    return 1.0 / (1.0 + math.exp(-k * x))


def update_strategy_confidence(
    *,
    completed_orders,
    window: int = 30,
) -> StrategyFeedback:
    """
    Compute a confidence multiplier from recent ``Order`` rows.

    ``completed_orders`` should be an iterable of objects exposing
    ``status``, ``approved_notional``, ``filled_notional``,
    ``average_fill_price``, and ``realized_pnl`` (or ``metadata.pnl``).
    Only the last ``window`` records are considered.
    """
    orders = list(completed_orders)[:window]
    if not orders:
        return StrategyFeedback(
            win_rate=0.0,
            average_r=0.0,
            sharpe_like=0.0,
            sample_size=0,
            multiplier=1.0,
            payload={"reason": "no_history"},
        )

    pnl_values: list[float] = []
    risk_values: list[float] = []

    for order in orders:
        pnl = getattr(order, "realized_pnl", None)
        if pnl is None:
            metadata = getattr(order, "metadata", None) or {}
            pnl = metadata.get("pnl")
        try:
            pnl_f = float(Decimal(str(pnl))) if pnl is not None else 0.0
        except Exception:
            pnl_f = 0.0
        pnl_values.append(pnl_f)

        notional = getattr(order, "approved_notional", None) or 0
        try:
            notional_f = float(Decimal(str(notional)))
        except Exception:
            notional_f = 0.0
        risk_values.append(max(notional_f * 0.02, 1.0))  # assume 2% risk

    wins = sum(1 for v in pnl_values if v > 0)
    win_rate = wins / len(pnl_values)

    rs = [pnl / risk for pnl, risk in zip(pnl_values, risk_values)]
    avg_r = sum(rs) / len(rs)

    if len(rs) > 1:
        mean = avg_r
        var = sum((r - mean) ** 2 for r in rs) / (len(rs) - 1)
        std = math.sqrt(var) if var > 0 else 0.0
        sharpe_like = (mean / std) if std > 0 else mean
    else:
        sharpe_like = avg_r

    # Combine win_rate (0..1, neutral=0.5), avg_r (centered at 0),
    # sharpe_like (centered at 0). We push the inputs through a logistic to
    # obtain a stable multiplier in [0.5, 1.5].
    score = (
        (win_rate - 0.5) * 1.5
        + math.tanh(avg_r) * 0.7
        + math.tanh(sharpe_like / 2) * 0.4
    )
    multiplier = 0.5 + _logistic(score, k=2) * 1.0  # 0.5 .. 1.5

    return StrategyFeedback(
        win_rate=round(win_rate, 4),
        average_r=round(avg_r, 4),
        sharpe_like=round(sharpe_like, 4),
        sample_size=len(pnl_values),
        multiplier=round(multiplier, 4),
        payload={
            "pnl_sum": round(sum(pnl_values), 2),
            "wins": wins,
            "losses": len(pnl_values) - wins,
            "score": round(score, 4),
        },
    )
