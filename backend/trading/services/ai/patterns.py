"""
Pattern detection on top of computed features.

We deliberately keep this rule-based and explainable. The goal is not to
replace a deep model but to expose interpretable features that ML can pick
up later.

Detected patterns:

- ``BREAKOUT_UP``    — close crosses above prior high + Bollinger high
- ``BREAKOUT_DOWN``  — close crosses below prior low + Bollinger low
- ``REVERSAL_UP``    — RSI < 30 + bullish MACD cross + close > prev close
- ``REVERSAL_DOWN``  — RSI > 70 + bearish MACD cross + close < prev close
- ``TREND_CONTINUATION_UP``   — uptrend, close above SMA20 with momentum
- ``TREND_CONTINUATION_DOWN`` — downtrend, close below SMA20 with momentum
- ``SQUEEZE``        — Bollinger width compressing → impending move
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DetectedPattern:
    label: str
    direction: str  # BUY / SELL / NEUTRAL
    strength: float  # 0..1
    description: str


def _last_two(series, key: str):
    if series is None or series.empty or key not in series.columns:
        return None, None
    if len(series) < 2:
        return None, None
    return float(series.iloc[-2][key]), float(series.iloc[-1][key])


def detect_patterns(features) -> list[DetectedPattern]:
    series = getattr(features, "series", None)
    if series is None or len(series) < 30:
        return []

    snapshot = getattr(features, "snapshot", {}) or {}
    last = series.iloc[-1]
    prev = series.iloc[-2]
    found: list[DetectedPattern] = []

    close = float(last["close"])
    prev_close = float(prev["close"])
    bb_high = float(last["bb_high"])
    bb_low = float(last["bb_low"])
    bb_width = float(last.get("bb_width", 0))
    rsi = float(last["rsi_14"])
    macd = float(last["macd"])
    macd_signal = float(last["macd_signal"])
    prev_macd = float(prev["macd"])
    prev_macd_signal = float(prev["macd_signal"])
    sma_20 = float(last.get("sma_20", close))
    sma_50 = float(last.get("sma_50", close))

    recent_high = float(series["high"].iloc[-20:-1].max()) if len(series) >= 20 else close
    recent_low = float(series["low"].iloc[-20:-1].min()) if len(series) >= 20 else close

    # ── Breakouts
    if close > recent_high and close > bb_high:
        strength = min(1.0, (close - recent_high) / max(recent_high * 0.005, 1e-9))
        found.append(
            DetectedPattern(
                "BREAKOUT_UP", "BUY", strength,
                f"Close {close:.4f} above 20-bar high {recent_high:.4f} and BB high.",
            )
        )

    if close < recent_low and close < bb_low:
        strength = min(1.0, (recent_low - close) / max(recent_low * 0.005, 1e-9))
        found.append(
            DetectedPattern(
                "BREAKOUT_DOWN", "SELL", strength,
                f"Close {close:.4f} below 20-bar low {recent_low:.4f} and BB low.",
            )
        )

    # ── Reversals
    macd_cross_up = prev_macd <= prev_macd_signal and macd > macd_signal
    macd_cross_down = prev_macd >= prev_macd_signal and macd < macd_signal

    if rsi < 30 and macd_cross_up and close > prev_close:
        found.append(
            DetectedPattern(
                "REVERSAL_UP", "BUY", 0.7,
                f"RSI oversold ({rsi:.1f}) + bullish MACD cross + green candle.",
            )
        )

    if rsi > 70 and macd_cross_down and close < prev_close:
        found.append(
            DetectedPattern(
                "REVERSAL_DOWN", "SELL", 0.7,
                f"RSI overbought ({rsi:.1f}) + bearish MACD cross + red candle.",
            )
        )

    # ── Trend continuation
    if close > sma_20 > sma_50 and macd > macd_signal:
        found.append(
            DetectedPattern(
                "TREND_CONTINUATION_UP", "BUY", 0.55,
                "Uptrend (SMA20>SMA50) + close above SMA20 + MACD positive.",
            )
        )

    if close < sma_20 < sma_50 and macd < macd_signal:
        found.append(
            DetectedPattern(
                "TREND_CONTINUATION_DOWN", "SELL", 0.55,
                "Downtrend (SMA20<SMA50) + close below SMA20 + MACD negative.",
            )
        )

    # ── Squeeze (impending breakout)
    if 0 < bb_width < 0.025:
        found.append(
            DetectedPattern(
                "SQUEEZE", "NEUTRAL", 0.5,
                f"Bollinger width compressed ({bb_width:.4f}); breakout likely.",
            )
        )

    return found
