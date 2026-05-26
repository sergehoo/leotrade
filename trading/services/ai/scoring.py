"""
Multi-factor opportunity scoring.

The legacy ``OpportunityScoringService`` stitched a few tanh and clamp
calls together — the formulas were neither calibrated nor side-aware
(an oversold RSI yielded a high "score" with no notion of BUY vs SELL).

This new scorer:

- Splits scoring into independent dimensions: ``trend``, ``momentum``,
  ``volatility``, ``setup``, ``volume``.
- Weights each dimension by the detected market regime.
- Outputs an explicit ``side`` (BUY/SELL) and a ``confidence`` 0..1 with
  a transparent breakdown (every score has a ``payload`` you can show in
  the UI for explainability).
- Applies a multiplier from past trade feedback (see :mod:`feedback`).

Returned :class:`OpportunityScore` is a dataclass that maps cleanly to
``MarketOpportunity`` fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .features import FeatureBundle
from .regime import MarketRegime, detect_regime
from .patterns import DetectedPattern, detect_patterns


# Regime → (trend, momentum, setup, volatility, volume) weight tuple.
_REGIME_WEIGHTS = {
    "TREND_UP":        (0.30, 0.30, 0.15, 0.10, 0.15),
    "TREND_DOWN":      (0.30, 0.30, 0.15, 0.10, 0.15),
    "RANGE":           (0.10, 0.20, 0.40, 0.20, 0.10),
    "HIGH_VOL":        (0.15, 0.15, 0.20, 0.40, 0.10),
    "UNCLEAR":         (0.20, 0.20, 0.30, 0.20, 0.10),
    "UNKNOWN":         (0.20, 0.20, 0.30, 0.20, 0.10),
}


@dataclass
class OpportunityScore:
    side: str                   # BUY / SELL / HOLD
    confidence: float           # 0..1
    setup_score: float
    trend_score: float
    momentum_score: float
    volatility_score: float     # higher = more volatile (risk)
    volume_score: float
    overall_score: float
    reward_score: float
    risk_score: float
    regime: str
    patterns: list[DetectedPattern] = field(default_factory=list)
    payload: dict = field(default_factory=dict)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _trend_component(snapshot: dict) -> tuple[float, str]:
    close = snapshot.get("close", 0)
    ema_20 = snapshot.get("ema_20", close)
    ema_50 = snapshot.get("ema_50", close)
    sma_20 = snapshot.get("sma_20", close)
    sma_50 = snapshot.get("sma_50", close)

    bull = 0
    bear = 0

    if close and ema_20 and close > ema_20:
        bull += 1
    elif close and ema_20 and close < ema_20:
        bear += 1

    if sma_20 and sma_50 and sma_20 > sma_50:
        bull += 1
    elif sma_20 and sma_50 and sma_20 < sma_50:
        bear += 1

    if ema_20 and ema_50 and ema_20 > ema_50:
        bull += 1
    elif ema_20 and ema_50 and ema_20 < ema_50:
        bear += 1

    score = bull / 3 if bull >= bear else -bear / 3
    side = "BUY" if score > 0 else ("SELL" if score < 0 else "HOLD")
    return abs(score), side


def _momentum_component(snapshot: dict) -> tuple[float, str]:
    macd = snapshot.get("macd", 0)
    macd_signal = snapshot.get("macd_signal", 0)
    macd_hist = snapshot.get("macd_hist", 0)
    rsi = snapshot.get("rsi_14", 50)
    returns_5 = snapshot.get("returns_5", 0)

    bull_strength = 0.0
    bear_strength = 0.0

    if macd > macd_signal:
        bull_strength += 0.3
    elif macd < macd_signal:
        bear_strength += 0.3

    if macd_hist > 0:
        bull_strength += 0.2
    elif macd_hist < 0:
        bear_strength += 0.2

    if rsi > 55:
        bull_strength += min(0.3, (rsi - 55) / 100)
    elif rsi < 45:
        bear_strength += min(0.3, (45 - rsi) / 100)

    if returns_5 > 0:
        bull_strength += min(0.2, returns_5 * 8)
    elif returns_5 < 0:
        bear_strength += min(0.2, -returns_5 * 8)

    if bull_strength > bear_strength:
        return _clamp(bull_strength), "BUY"
    if bear_strength > bull_strength:
        return _clamp(bear_strength), "SELL"
    return 0.0, "HOLD"


def _volatility_component(snapshot: dict) -> float:
    """Higher = more volatile (more risk). Used in risk scoring."""
    close = snapshot.get("close", 0) or 1
    atr = snapshot.get("atr_14", 0)
    vol_20 = snapshot.get("volatility_20", 0)
    bb_width = snapshot.get("bb_width", 0)

    score = 0.0
    if close:
        score += min(1.0, (atr / close) * 20)
    score += min(1.0, vol_20 * 25)
    score += min(1.0, bb_width * 10)
    return _clamp(score / 3)


def _setup_component(snapshot: dict, side: str) -> float:
    """How clean is the technical setup for the chosen side."""
    bb_pos = snapshot.get("bb_pos", 0.5)
    rsi = snapshot.get("rsi_14", 50)

    if side == "BUY":
        # BUY favoured near lower band, RSI bouncing from oversold
        bb_part = 1 - bb_pos
        rsi_part = 1 - abs(rsi - 40) / 60 if rsi <= 60 else 0.2
    elif side == "SELL":
        bb_part = bb_pos
        rsi_part = 1 - abs(rsi - 60) / 60 if rsi >= 40 else 0.2
    else:
        bb_part = 0
        rsi_part = 0

    return _clamp((bb_part + rsi_part) / 2)


def _volume_component(snapshot: dict) -> float:
    ratio = snapshot.get("volume_ratio", 1)
    return _clamp((ratio - 1) / 2 + 0.5)


def _aggregate_side(votes: list[tuple[float, str]]) -> tuple[str, float]:
    bull = sum(strength for strength, side in votes if side == "BUY")
    bear = sum(strength for strength, side in votes if side == "SELL")
    if bull == 0 and bear == 0:
        return "HOLD", 0.0
    if bull >= bear:
        return "BUY", bull / max(bull + bear, 1e-9)
    return "SELL", bear / max(bull + bear, 1e-9)


def score_opportunity(
    features: FeatureBundle,
    *,
    regime: Optional[MarketRegime] = None,
    feedback_multiplier: float = 1.0,
) -> OpportunityScore:
    """
    Compute a multi-factor :class:`OpportunityScore` from features.

    Parameters
    ----------
    features
        Output of :func:`compute_features`.
    regime
        Optional pre-computed regime; if ``None`` we run :func:`detect_regime`.
    feedback_multiplier
        From :mod:`feedback`, dampens or boosts confidence based on this
        strategy's recent track record. ``1.0`` is neutral.
    """
    snapshot = features.snapshot if features else {}
    if not snapshot:
        return OpportunityScore(
            side="HOLD", confidence=0.0,
            setup_score=0.0, trend_score=0.0, momentum_score=0.0,
            volatility_score=0.0, volume_score=0.0,
            overall_score=0.0, reward_score=0.0, risk_score=0.0,
            regime="UNKNOWN",
            payload={"reason": "no_features"},
        )

    regime = regime or detect_regime(features)

    trend_strength, trend_side = _trend_component(snapshot)
    momentum_strength, momentum_side = _momentum_component(snapshot)

    side, side_confidence = _aggregate_side(
        [(trend_strength, trend_side), (momentum_strength, momentum_side)]
    )

    setup_score = _setup_component(snapshot, side)
    volatility_score = _volatility_component(snapshot)
    volume_score = _volume_component(snapshot)

    weights = _REGIME_WEIGHTS.get(regime.label, _REGIME_WEIGHTS["UNCLEAR"])
    w_trend, w_momentum, w_setup, w_vol, w_volume = weights

    overall = (
        w_trend * trend_strength
        + w_momentum * momentum_strength
        + w_setup * setup_score
        + w_vol * (1 - volatility_score)  # less volatile = better
        + w_volume * volume_score
    )

    patterns = detect_patterns(features)
    pattern_boost = 0.0
    for p in patterns:
        if p.direction == side:
            pattern_boost += 0.10 * p.strength
        elif p.direction != "NEUTRAL" and p.direction != side:
            pattern_boost -= 0.05 * p.strength

    raw_confidence = _clamp(overall + pattern_boost) * side_confidence
    confidence = _clamp(raw_confidence * feedback_multiplier)

    reward_score = _clamp(0.6 * momentum_strength + 0.2 * volume_score + 0.2 * (1 - volatility_score))
    risk_score = volatility_score

    payload = {
        "regime": regime.label,
        "regime_confidence": regime.confidence,
        "regime_payload": regime.payload,
        "weights": {
            "trend": w_trend, "momentum": w_momentum, "setup": w_setup,
            "volatility": w_vol, "volume": w_volume,
        },
        "trend_side": trend_side,
        "momentum_side": momentum_side,
        "side_confidence": side_confidence,
        "pattern_boost": pattern_boost,
        "feedback_multiplier": feedback_multiplier,
        "patterns": [
            {"label": p.label, "direction": p.direction, "strength": p.strength}
            for p in patterns
        ],
    }

    return OpportunityScore(
        side=side,
        confidence=round(confidence, 4),
        setup_score=round(setup_score, 4),
        trend_score=round(trend_strength, 4),
        momentum_score=round(momentum_strength, 4),
        volatility_score=round(volatility_score, 4),
        volume_score=round(volume_score, 4),
        overall_score=round(_clamp(overall), 4),
        reward_score=round(reward_score, 4),
        risk_score=round(risk_score, 4),
        regime=regime.label,
        patterns=patterns,
        payload=payload,
    )
