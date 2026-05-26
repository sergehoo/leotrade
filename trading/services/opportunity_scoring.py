from __future__ import annotations

from math import tanh


class OpportunityScoringService:
    @staticmethod
    def clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
        return max(min_value, min(max_value, value))

    @classmethod
    def score(cls, features: dict) -> dict:
        rsi = float(features.get("rsi_14") or 50)
        macd = float(features.get("macd") or 0)
        macd_signal = float(features.get("macd_signal") or 0)
        returns_1 = float(features.get("returns_1") or 0)
        returns_5 = float(features.get("returns_5") or 0)
        volatility_20 = float(features.get("volatility_20") or 0)
        atr_14 = float(features.get("atr_14") or 0)
        close = float(features.get("close") or 0)
        sma_20 = float(features.get("sma_20") or 0)
        sma_50 = float(features.get("sma_50") or 0)
        bb_high = float(features.get("bb_high") or 0)
        bb_low = float(features.get("bb_low") or 0)

        trend_bias = 0.5
        if close and sma_20 and sma_50:
            if close > sma_20 > sma_50:
                trend_bias = 0.85
            elif close < sma_20 < sma_50:
                trend_bias = 0.80
            else:
                trend_bias = 0.50

        momentum_score = cls.clamp((tanh((returns_1 + returns_5) * 8) + 1) / 2)
        macd_score = cls.clamp((tanh((macd - macd_signal) * 5) + 1) / 2)

        if rsi < 30:
            rsi_score = 0.80
        elif rsi > 70:
            rsi_score = 0.80
        else:
            rsi_score = 1 - abs(rsi - 50) / 50

        band_position_score = 0.50
        if close and bb_high and bb_low and bb_high > bb_low:
            ratio = (close - bb_low) / (bb_high - bb_low)
            band_position_score = cls.clamp(ratio)

        setup_score = cls.clamp((trend_bias * 0.35) + (momentum_score * 0.20) + (macd_score * 0.25) + (rsi_score * 0.20))
        risk_score = cls.clamp((volatility_20 * 3) + (atr_14 / close if close else 0))
        reward_score = cls.clamp((abs(returns_5) * 3) + (abs(macd - macd_signal) * 0.2) + (band_position_score * 0.2))
        confidence_score = cls.clamp((setup_score * 0.45) + ((1 - risk_score) * 0.20) + (reward_score * 0.35))
        overall_score = cls.clamp((confidence_score * 0.50) + (setup_score * 0.25) + (reward_score * 0.20) + ((1 - risk_score) * 0.05))

        return {
            "confidence_score": round(confidence_score, 4),
            "setup_score": round(setup_score, 4),
            "risk_score": round(risk_score, 4),
            "reward_score": round(reward_score, 4),
            "overall_score": round(overall_score, 4),
        }

    @staticmethod
    def choose_direction(features: dict) -> str:
        close = float(features.get("close") or 0)
        sma_20 = float(features.get("sma_20") or 0)
        sma_50 = float(features.get("sma_50") or 0)
        macd = float(features.get("macd") or 0)
        macd_signal = float(features.get("macd_signal") or 0)
        rsi = float(features.get("rsi_14") or 50)

        bullish = 0
        bearish = 0

        if close and sma_20 and close > sma_20:
            bullish += 1
        elif close and sma_20 and close < sma_20:
            bearish += 1

        if sma_20 and sma_50 and sma_20 > sma_50:
            bullish += 1
        elif sma_20 and sma_50 and sma_20 < sma_50:
            bearish += 1

        if macd > macd_signal:
            bullish += 1
        elif macd < macd_signal:
            bearish += 1

        if rsi > 55:
            bullish += 1
        elif rsi < 45:
            bearish += 1

        return "BUY" if bullish >= bearish else "SELL"