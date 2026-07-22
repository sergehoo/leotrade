"""
Technical feature engineering for Lyneci AI scoring.

The legacy ``MarketScannerService._extract_features`` produced fake
indicators (``rsi_14 = 60 if close >= prev_close else 40``). This module
computes the real thing using the ``ta`` library (already in
requirements.txt) on a list of candles.

Inputs
------

A chronologically-ordered list of objects exposing ``open_time``, ``open``,
``high``, ``low``, ``close``, ``volume`` (Django Candle models or dicts).
The most recent candle should be the LAST element of the list — but the
implementation also detects descending order and reverses if needed.

Outputs
-------

A :class:`FeatureBundle` containing both:

- ``snapshot``: scalar values for the latest candle (for scoring).
- ``series``: pandas DataFrame with the full indicator history (for ML
  training, regime detection, pattern detection).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

logger = logging.getLogger(__name__)


@dataclass
class FeatureBundle:
    snapshot: dict[str, float] = field(default_factory=dict)
    series: Any = None  # pandas.DataFrame, kept generic to avoid import at module load

    def get(self, key: str, default: float = 0.0) -> float:
        value = self.snapshot.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default


def _to_dataframe(candles: Iterable):
    import pandas as pd

    rows = []
    for c in candles:
        get = (lambda obj, k: getattr(obj, k, None)) if not isinstance(c, dict) else (lambda obj, k: obj.get(k))
        rows.append({
            "open_time": get(c, "open_time"),
            "open": float(get(c, "open") or 0),
            "high": float(get(c, "high") or 0),
            "low": float(get(c, "low") or 0),
            "close": float(get(c, "close") or 0),
            "volume": float(get(c, "volume") or 0),
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    if df["open_time"].notna().any():
        df = df.sort_values("open_time").reset_index(drop=True)
    return df


def compute_features(candles: Iterable) -> FeatureBundle:
    """
    Compute a robust feature set from a list of candles.

    Indicators
    ----------

    - SMA 20 / SMA 50 / EMA 20 / EMA 50
    - RSI 14
    - MACD (12, 26, 9) with signal and histogram
    - ATR 14 (volatility)
    - Bollinger Bands (20, 2σ): high / mid / low / width / position
    - Stochastic %K %D
    - Returns 1 / 5 / 20
    - Realized volatility 20
    - Volume ratio (current / SMA 20)
    """
    try:
        import numpy as np  # noqa: F401
        import pandas as pd
        from ta.momentum import RSIIndicator, StochasticOscillator
        from ta.trend import MACD, EMAIndicator, SMAIndicator
        from ta.volatility import AverageTrueRange, BollingerBands
    except Exception as exc:
        logger.error("Missing TA libs for feature computation: %s", exc)
        return FeatureBundle()

    df = _to_dataframe(candles)
    if df.empty or len(df) < 30:
        return FeatureBundle()

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # Trend
    df["sma_20"] = SMAIndicator(close=close, window=20, fillna=True).sma_indicator()
    df["sma_50"] = SMAIndicator(close=close, window=50, fillna=True).sma_indicator()
    df["ema_20"] = EMAIndicator(close=close, window=20, fillna=True).ema_indicator()
    df["ema_50"] = EMAIndicator(close=close, window=50, fillna=True).ema_indicator()

    # Momentum
    df["rsi_14"] = RSIIndicator(close=close, window=14, fillna=True).rsi()
    macd = MACD(close=close, window_fast=12, window_slow=26, window_sign=9, fillna=True)
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()

    # Stochastic
    stoch = StochasticOscillator(high=high, low=low, close=close, window=14, smooth_window=3, fillna=True)
    df["stoch_k"] = stoch.stoch()
    df["stoch_d"] = stoch.stoch_signal()

    # Volatility
    df["atr_14"] = AverageTrueRange(high=high, low=low, close=close, window=14, fillna=True).average_true_range()
    bb = BollingerBands(close=close, window=20, window_dev=2, fillna=True)
    df["bb_high"] = bb.bollinger_hband()
    df["bb_low"] = bb.bollinger_lband()
    df["bb_mid"] = bb.bollinger_mavg()
    df["bb_width"] = (df["bb_high"] - df["bb_low"]) / df["bb_mid"].where(df["bb_mid"] != 0, 1)
    df["bb_pos"] = ((close - df["bb_low"]) / (df["bb_high"] - df["bb_low"]).where(
        (df["bb_high"] - df["bb_low"]) != 0, 1
    )).clip(0, 1)

    # Returns
    df["returns_1"] = close.pct_change(1).fillna(0)
    df["returns_5"] = close.pct_change(5).fillna(0)
    df["returns_20"] = close.pct_change(20).fillna(0)

    # Realized volatility
    df["volatility_20"] = df["returns_1"].rolling(window=20).std().fillna(0)

    # Volume normalization
    vol_sma = volume.rolling(window=20).mean().fillna(volume.mean())
    df["volume_ratio"] = (volume / vol_sma.where(vol_sma > 0, 1)).fillna(1)

    last = df.iloc[-1].to_dict()
    snapshot = {k: float(v) for k, v in last.items() if k != "open_time"}
    snapshot["open_time"] = (
        last["open_time"].isoformat() if hasattr(last["open_time"], "isoformat") else None
    )
    return FeatureBundle(snapshot=snapshot, series=df)
