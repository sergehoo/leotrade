from __future__ import annotations

from statistics import mean

from market.models import Asset, MarketFeature, Timeframe
from trading.models_hedge_fund import MarketRegimeState


class MarketRegimeAgent:
    @classmethod
    def detect(cls, timeframe_code: str = "4h"):
        timeframe = Timeframe.objects.filter(code=timeframe_code).first()
        if not timeframe:
            raise ValueError(f"Timeframe {timeframe_code} introuvable.")

        features = (
            MarketFeature.objects
            .filter(timeframe=timeframe, asset__is_active=True)
            .select_related("asset")
            .order_by("asset_id", "-candle_time")
        )

        latest_by_asset = {}
        for f in features:
            if f.asset_id not in latest_by_asset:
                latest_by_asset[f.asset_id] = f

        rows = list(latest_by_asset.values())
        if not rows:
            return MarketRegimeState.objects.create(
                timeframe=timeframe,
                regime="MIXED",
                confidence=0.20,
                summary="Aucune donnée marché disponible.",
                payload={},
            )

        bullish = 0
        bearish = 0
        vols = []
        breadth = []

        for f in rows:
            close_above = 0
            if f.sma_20 and f.sma_50:
                if f.sma_20 > f.sma_50:
                    bullish += 1
                    close_above = 1
                elif f.sma_20 < f.sma_50:
                    bearish += 1
                    close_above = -1

            vols.append(float(f.volatility_20 or 0))
            breadth.append(close_above)

        total = len(rows)
        bull_ratio = bullish / total if total else 0
        bear_ratio = bearish / total if total else 0
        avg_vol = mean(vols) if vols else 0
        avg_breadth = mean(breadth) if breadth else 0

        regime = "MIXED"
        confidence = 0.50
        summary = "Régime mixte."
        trend_score = max(bull_ratio, bear_ratio)
        volatility_score = min(1.0, avg_vol * 5)
        breadth_score = abs(avg_breadth)
        correlation_stress_score = min(1.0, (bull_ratio + bear_ratio) / 2)

        if avg_vol > 0.10:
            regime = "HIGH_VOLATILITY"
            confidence = 0.85
            summary = "Volatilité élevée sur l’univers observé."
        elif bull_ratio >= 0.65:
            regime = "BULL_TREND"
            confidence = min(0.95, 0.55 + bull_ratio * 0.4)
            summary = "Biais haussier confirmé sur la majorité des actifs."
        elif bear_ratio >= 0.65:
            regime = "BEAR_TREND"
            confidence = min(0.95, 0.55 + bear_ratio * 0.4)
            summary = "Biais baissier confirmé sur la majorité des actifs."
        elif abs(avg_breadth) < 0.20:
            regime = "SIDEWAYS"
            confidence = 0.70
            summary = "Marché latéral / en range."

        return MarketRegimeState.objects.create(
            timeframe=timeframe,
            regime=regime,
            confidence=confidence,
            trend_score=round(trend_score, 4),
            volatility_score=round(volatility_score, 4),
            breadth_score=round(breadth_score, 4),
            correlation_stress_score=round(correlation_stress_score, 4),
            summary=summary,
            payload={
                "bull_ratio": bull_ratio,
                "bear_ratio": bear_ratio,
                "avg_volatility": avg_vol,
                "avg_breadth": avg_breadth,
                "asset_count": total,
            },
        )