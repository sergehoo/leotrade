"""
ai_engine/providers/heuristic.py
================================

Fallback déterministe — utilisé quand aucun LLM n'est disponible (réseau down,
tokens manquants, quota dépassé). Reproduit la logique historique mais avec
une sortie typée AIDecision.

Avantage : ZÉRO dépendance externe, ZÉRO latence, ZÉRO coût.
Limite : pas de raisonnement contextuel, juste des seuils sur indicateurs.
"""

from __future__ import annotations

from decimal import Decimal

from .base import BaseAIProvider, MarketContext, AIDecision


class HeuristicProvider(BaseAIProvider):
    name = "HEURISTIC"
    model_name = "rules-v1"

    def is_available(self) -> bool:
        return True  # toujours dispo

    def advise(self, context: MarketContext) -> AIDecision:
        ind = context.indicators or {}
        rsi = float(ind.get("rsi", 50) or 50)
        macd_hist = float(ind.get("macd_hist", 0) or 0)
        sma_fast = float(ind.get("sma_20", 0) or 0)
        sma_slow = float(ind.get("sma_50", 0) or 0)
        atr = float(ind.get("atr", 0) or 0)

        last_price = float(context.last_price or 0)

        # Score directionnel : combiner RSI, MACD histogram, croisement SMA
        bullish = 0
        bearish = 0

        if rsi < 35: bullish += 1
        elif rsi > 65: bearish += 1
        if macd_hist > 0: bullish += 1
        elif macd_hist < 0: bearish += 1
        if sma_fast > sma_slow > 0: bullish += 1
        elif sma_slow > sma_fast > 0: bearish += 1

        if bullish > bearish:
            direction = "LONG"
            score = bullish / 3.0
        elif bearish > bullish:
            direction = "SHORT"
            score = bearish / 3.0
        else:
            return AIDecision(
                decision="WATCH",
                confidence=0.3,
                rationale="Signaux contradictoires — attendre confirmation.",
                risks=["divergence_indicators"],
                provider=self.name,
                model_name=self.model_name,
            )

        # Stake : 1% du cash dispo, plafonné par max_risk_per_trade_pct
        risk_pct = (context.max_risk_per_trade_pct or 1.0) / 100.0
        cash = float(context.available_cash or 0)
        suggested_stake = Decimal(str(round(cash * risk_pct, 2))) if cash > 0 else None

        # SL/TP basés sur ATR
        sl = tp = None
        if atr > 0 and last_price > 0:
            if direction == "LONG":
                sl = Decimal(str(round(last_price - 1.5 * atr, 6)))
                tp = Decimal(str(round(last_price + 3.0 * atr, 6)))
            else:
                sl = Decimal(str(round(last_price + 1.5 * atr, 6)))
                tp = Decimal(str(round(last_price - 3.0 * atr, 6)))
            expected_rr = 2.0
        else:
            expected_rr = None

        # Décision basée sur score
        if score >= 0.66:
            decision = "EXECUTE"
        elif score >= 0.33:
            decision = "PLAN"
        else:
            decision = "WATCH"

        # Bloque si pas assez de cash
        if suggested_stake is not None and float(suggested_stake) <= 0:
            decision = "REJECT"
            return AIDecision(
                decision=decision,
                confidence=0.0,
                direction=direction,
                rationale="Cash disponible insuffisant pour ce trade.",
                risks=["insufficient_cash"],
                provider=self.name, model_name=self.model_name,
            )
        # Bloque si trop de positions ouvertes
        if (context.max_open_positions is not None
                and context.current_open_positions >= context.max_open_positions):
            return AIDecision(
                decision="REJECT",
                confidence=0.0,
                direction=direction,
                rationale="Limite de positions ouvertes atteinte.",
                risks=["max_open_positions_reached"],
                provider=self.name, model_name=self.model_name,
            )

        return AIDecision(
            decision=decision,
            confidence=score,
            direction=direction,
            expected_rr=expected_rr,
            suggested_stake=suggested_stake,
            suggested_stop_loss=sl,
            suggested_take_profit=tp,
            rationale=(
                f"Score directionnel {score:.2f} ({direction}). "
                f"RSI={rsi:.1f}, MACD_hist={macd_hist:.4f}, SMA20/50={sma_fast:.2f}/{sma_slow:.2f}. "
                f"SL/TP basés sur ATR={atr:.6f}."
            ),
            risks=[],
            provider=self.name,
            model_name=self.model_name,
        )
