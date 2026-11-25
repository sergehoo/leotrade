"""
Market regime detection.

A signal valid in a trending market is often noise in a ranging one.
This module classifies the current state into one of:

- ``TREND_UP``  / ``TREND_DOWN``
- ``RANGE``     (sideways, low ATR, mean-reverting)
- ``HIGH_VOL``  (chop, ATR spike, no clear direction)

The classification feeds back into scoring weights — e.g. breakouts are
worth more in TREND, mean-reversion setups are worth more in RANGE.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MarketRegime:
    label: str
    confidence: float  # 0..1
    payload: dict


def detect_regime(features) -> MarketRegime:
    """Classify regime from a :class:`FeatureBundle`."""
    snapshot = getattr(features, "snapshot", {}) or {}

    close = snapshot.get("close", 0)
    sma_20 = snapshot.get("sma_20", close)
    sma_50 = snapshot.get("sma_50", close)
    bb_width = snapshot.get("bb_width", 0)
    atr_14 = snapshot.get("atr_14", 0)
    volatility_20 = snapshot.get("volatility_20", 0)
    rsi_14 = snapshot.get("rsi_14", 50)

    if close <= 0:
        return MarketRegime("UNKNOWN", 0.0, {"reason": "no_close"})

    atr_ratio = atr_14 / close if close else 0
    is_high_vol = volatility_20 > 0.04 or atr_ratio > 0.05

    trend_up = sma_20 > sma_50 and close > sma_20
    trend_down = sma_20 < sma_50 and close < sma_20

    payload = {
        "atr_ratio": atr_ratio,
        "bb_width": bb_width,
        "volatility_20": volatility_20,
        "rsi_14": rsi_14,
        "sma_20": sma_20,
        "sma_50": sma_50,
    }

    if is_high_vol and not (trend_up or trend_down):
        return MarketRegime("HIGH_VOL", 0.7, payload)

    if trend_up:
        # Confidence increases with separation between SMAs
        sep = abs(sma_20 - sma_50) / max(sma_50, 1e-9)
        confidence = max(0.5, min(0.95, 0.5 + sep * 8))
        return MarketRegime("TREND_UP", confidence, payload)

    if trend_down:
        sep = abs(sma_20 - sma_50) / max(sma_50, 1e-9)
        confidence = max(0.5, min(0.95, 0.5 + sep * 8))
        return MarketRegime("TREND_DOWN", confidence, payload)

    # Range: tight Bollinger, RSI hovering around 50
    if bb_width < 0.04 and 35 < rsi_14 < 65:
        return MarketRegime("RANGE", 0.7, payload)

    return MarketRegime("UNCLEAR", 0.4, payload)
