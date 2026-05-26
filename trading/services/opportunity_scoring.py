from __future__ import annotations

from math import tanh


class OpportunityScoringService:
    @staticmethod
    def clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
        return max(min_value, min(max_value, value))

    @classmethod
    def score(cls, features: dict) -> dict:
        rsi           = float(features.get("rsi_14") or 50)
        macd          = float(features.get("macd") or 0)
        macd_signal   = float(features.get("macd_signal") or 0)
        returns_1     = float(features.get("returns_1") or 0)
        returns_5     = float(features.get("returns_5") or 0)
        volatility_20 = float(features.get("volatility_20") or 0)
        atr_14        = float(features.get("atr_14") or 0)
        close         = float(features.get("close") or 0)
        sma_20        = float(features.get("sma_20") or 0)
        sma_50        = float(features.get("sma_50") or 0)
        bb_high       = float(features.get("bb_high") or 0)
        bb_low        = float(features.get("bb_low") or 0)

        # ── Tendance (trend_bias) ─────────────────────────────────────────────
        # Séparation bullish / bearish pour ne pas pénaliser un trend clair
        trend_bias = 0.50
        if close and sma_20 and sma_50:
            if close > sma_20 > sma_50:   # Uptrend aligné
                trend_bias = 0.85
            elif close < sma_20 < sma_50: # Downtrend aligné
                trend_bias = 0.20         # Faible — risque de vente à découvert
            elif close > sma_20:          # Au-dessus SMA20 seulement
                trend_bias = 0.65
            elif close < sma_20:          # En dessous SMA20
                trend_bias = 0.35

        # ── Momentum ─────────────────────────────────────────────────────────
        momentum_score = cls.clamp((tanh((returns_1 + returns_5) * 8) + 1) / 2)

        # ── MACD crossover ───────────────────────────────────────────────────
        macd_score = cls.clamp((tanh((macd - macd_signal) * 5) + 1) / 2)

        # ── RSI — logique correcte ────────────────────────────────────────────
        # Survente (<30) = opportunité longue forte
        # Surachat (>70) = risque de retournement, score bas
        # Zone neutre [40-60] = signal modéré selon contexte
        if rsi < 30:
            rsi_score = 0.85   # Oversold — forte opportunité rebond
        elif rsi < 40:
            rsi_score = 0.70   # Zone de rebond probable
        elif rsi <= 60:
            rsi_score = 0.50   # Neutre
        elif rsi <= 70:
            rsi_score = 0.30   # Momentum chaud, attention
        else:
            rsi_score = 0.15   # Overbought — risque fort

        # ── Position dans les bandes de Bollinger ────────────────────────────
        # Proche du bas des bandes = potentiel de rebond (score élevé)
        # Proche du haut = risque de compression (score bas)
        band_position_score = 0.50
        if close and bb_high and bb_low and bb_high > bb_low:
            ratio = (close - bb_low) / (bb_high - bb_low)
            # Inverser : plus on est bas dans les bandes, meilleure l'opportunité
            band_position_score = cls.clamp(1.0 - ratio)

        # ── Scores composés ──────────────────────────────────────────────────
        setup_score = cls.clamp(
            (trend_bias      * 0.35)
            + (momentum_score  * 0.20)
            + (macd_score      * 0.25)
            + (rsi_score       * 0.20)
        )

        # Normalisation de la volatilité par rapport à l'ATR en %
        atr_pct = (atr_14 / close) if close else 0.0
        # Volatilité élevée = risque mais aussi reward possible
        risk_score = cls.clamp(volatility_20 * 2.0 + atr_pct * 10.0)

        reward_score = cls.clamp(
            abs(returns_5) * 3.0
            + abs(macd - macd_signal) * 0.2
            + band_position_score * 0.3
        )

        confidence_score = cls.clamp(
            (setup_score     * 0.45)
            + ((1 - risk_score) * 0.20)
            + (reward_score    * 0.35)
        )
        overall_score = cls.clamp(
            (confidence_score  * 0.50)
            + (setup_score     * 0.25)
            + (reward_score    * 0.20)
            + ((1 - risk_score) * 0.05)
        )

        return {
            "confidence_score":  round(confidence_score, 4),
            "setup_score":       round(setup_score, 4),
            "risk_score":        round(risk_score, 4),
            "reward_score":      round(reward_score, 4),
            "overall_score":     round(overall_score, 4),
            # Sous-scores exposés pour debug / audit
            "rsi_score":         round(rsi_score, 4),
            "macd_score":        round(macd_score, 4),
            "trend_bias":        round(trend_bias, 4),
            "momentum_score":    round(momentum_score, 4),
        }

    @staticmethod
    def choose_direction(features: dict) -> str:
        """
        Détermine la direction (BUY/SELL) en pondérant plusieurs signaux.
        Chaque signal vote avec un poids différent selon sa fiabilité.
        """
        close       = float(features.get("close") or 0)
        sma_20      = float(features.get("sma_20") or 0)
        sma_50      = float(features.get("sma_50") or 0)
        macd        = float(features.get("macd") or 0)
        macd_signal = float(features.get("macd_signal") or 0)
        rsi         = float(features.get("rsi_14") or 50)
        returns_5   = float(features.get("returns_5") or 0)

        bullish = 0.0
        bearish = 0.0

        # Signal 1 : position vs SMA20 (poids 1.5)
        if close and sma_20:
            if close > sma_20:
                bullish += 1.5
            else:
                bearish += 1.5

        # Signal 2 : alignement des SMA (poids 2.0 — forte tendance)
        if sma_20 and sma_50:
            if sma_20 > sma_50:
                bullish += 2.0
            else:
                bearish += 2.0

        # Signal 3 : MACD crossover (poids 1.5)
        if macd > macd_signal:
            bullish += 1.5
        elif macd < macd_signal:
            bearish += 1.5

        # Signal 4 : RSI — seuils asymétriques (poids 1.0)
        if rsi < 35:
            bullish += 1.0   # Survente = rebond probable
        elif rsi > 65:
            bearish += 1.0   # Surachat = retournement probable

        # Signal 5 : momentum récent 5 périodes (poids 0.5)
        if returns_5 > 0.01:
            bullish += 0.5
        elif returns_5 < -0.01:
            bearish += 0.5

        return "BUY" if bullish >= bearish else "SELL"
