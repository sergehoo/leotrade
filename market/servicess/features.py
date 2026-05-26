from __future__ import annotations

from math import sqrt
from statistics import mean, pstdev

from django.db import transaction

from market.models import Candle, MarketFeature


class FeatureComputationService:
    @staticmethod
    def _sma(values: list[float], period: int) -> float | None:
        if len(values) < period:
            return None
        return mean(values[-period:])

    @staticmethod
    def _ema(values: list[float], period: int) -> float | None:
        if len(values) < period:
            return None
        multiplier = 2 / (period + 1)
        ema = mean(values[:period])
        for price in values[period:]:
            ema = (price - ema) * multiplier + ema
        return ema

    @staticmethod
    def _rsi(values: list[float], period: int = 14) -> float | None:
        if len(values) < period + 1:
            return None

        gains = []
        losses = []

        for i in range(1, len(values)):
            delta = values[i] - values[i - 1]
            gains.append(max(delta, 0))
            losses.append(abs(min(delta, 0)))

        avg_gain = mean(gains[:period])
        avg_loss = mean(losses[:period])

        for i in range(period, len(gains)):
            avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
            avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _macd(values: list[float]) -> tuple[float | None, float | None]:
        if len(values) < 35:
            return None, None

        macd_series = []
        for i in range(len(values)):
            subset = values[: i + 1]
            ema12 = FeatureComputationService._ema(subset, 12)
            ema26 = FeatureComputationService._ema(subset, 26)
            if ema12 is not None and ema26 is not None:
                macd_series.append(ema12 - ema26)

        if not macd_series:
            return None, None

        macd_value = macd_series[-1]
        signal_value = FeatureComputationService._ema(macd_series, 9)
        return macd_value, signal_value

    @staticmethod
    def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float | None:
        if len(closes) < period + 1:
            return None

        trs = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            trs.append(tr)

        if len(trs) < period:
            return None

        atr = mean(trs[:period])
        for tr in trs[period:]:
            atr = ((atr * (period - 1)) + tr) / period
        return atr

    @staticmethod
    def _bollinger(values: list[float], period: int = 20, std_mult: float = 2.0) -> tuple[float | None, float | None]:
        if len(values) < period:
            return None, None

        window = values[-period:]
        m = mean(window)
        s = pstdev(window) if len(window) > 1 else 0
        return m + (s * std_mult), m - (s * std_mult)

    @staticmethod
    def _returns(closes: list[float], steps: int) -> float | None:
        if len(closes) <= steps:
            return None
        prev = closes[-(steps + 1)]
        if prev == 0:
            return None
        return (closes[-1] - prev) / prev

    @staticmethod
    def _volatility(closes: list[float], period: int = 20) -> float | None:
        if len(closes) < period + 1:
            return None

        returns = []
        for i in range(len(closes) - period, len(closes)):
            if i == 0:
                continue
            prev = closes[i - 1]
            if prev == 0:
                continue
            returns.append((closes[i] - prev) / prev)

        if len(returns) < 2:
            return None

        return pstdev(returns)

    @classmethod
    def build_feature_row(cls, candles) -> dict | None:
        candles = list(candles)
        if len(candles) < 20:
            return None

        closes = [float(c.close) for c in candles]
        highs = [float(c.high) for c in candles]
        lows = [float(c.low) for c in candles]

        rsi_14 = cls._rsi(closes, 14)
        macd, macd_signal = cls._macd(closes)
        sma_20 = cls._sma(closes, 20)
        sma_50 = cls._sma(closes, 50)
        atr_14 = cls._atr(highs, lows, closes, 14)
        bb_high, bb_low = cls._bollinger(closes, 20, 2.0)
        returns_1 = cls._returns(closes, 1)
        returns_5 = cls._returns(closes, 5)
        volatility_20 = cls._volatility(closes, 20)

        return {
            "rsi_14": rsi_14,
            "macd": macd,
            "macd_signal": macd_signal,
            "sma_20": sma_20,
            "sma_50": sma_50,
            "atr_14": atr_14,
            "bb_high": bb_high,
            "bb_low": bb_low,
            "returns_1": returns_1,
            "returns_5": returns_5,
            "volatility_20": volatility_20,
        }

    @classmethod
    @transaction.atomic
    def compute_for_asset_timeframe(cls, asset, timeframe, lookback: int = 300) -> dict:
        candles = list(
            Candle.objects
            .filter(asset=asset, timeframe=timeframe)
            .order_by("open_time")[:lookback]
        )

        if len(candles) < 20:
            return {
                "asset": asset.symbol,
                "timeframe": timeframe.code,
                "computed": 0,
                "reason": "not_enough_candles",
            }

        computed = 0

        for idx in range(20, len(candles) + 1):
            subset = candles[:idx]
            feature_values = cls.build_feature_row(subset)
            if not feature_values:
                continue

            candle = subset[-1]

            MarketFeature.objects.update_or_create(
                asset=asset,
                timeframe=timeframe,
                candle_time=candle.open_time,
                defaults=feature_values,
            )
            computed += 1

        return {
            "asset": asset.symbol,
            "timeframe": timeframe.code,
            "computed": computed,
        }