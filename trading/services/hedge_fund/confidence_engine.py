from __future__ import annotations

from trading.models_hedge_fund import ConfidenceAssessment, LearningSnapshot


class ConfidenceEngine:
    @classmethod
    def assess(cls, idea, regime_state=None, learning_snapshot=None, risk_state=None):
        raw = float(idea.confidence_score or 0)

        regime_adj = 0.0
        if regime_state:
            if regime_state.regime == "BULL_TREND" and idea.direction in ["BUY", "CALL"]:
                regime_adj += 0.08
            elif regime_state.regime == "BEAR_TREND" and idea.direction in ["SELL", "PUT"]:
                regime_adj += 0.08
            elif regime_state.regime == "HIGH_VOLATILITY":
                regime_adj -= 0.08
            elif regime_state.regime == "SIDEWAYS":
                regime_adj -= 0.03

        learning_adj = 0.0
        if learning_snapshot:
            learning_adj += (float(learning_snapshot.confidence_multiplier or 1.0) - 1.0)
            learning_adj -= float(learning_snapshot.drawdown_penalty or 0.0) * 0.2

        risk_adj = 0.0
        if risk_state:
            if risk_state.status == "BLOCK":
                risk_adj -= 0.30
            elif risk_state.status == "REDUCE":
                risk_adj -= 0.12
            elif risk_state.status == "CAUTION":
                risk_adj -= 0.05

        final_confidence = max(0.0, min(1.0, raw + regime_adj + learning_adj + risk_adj))
        sizing_score = max(0.0, min(1.0, (final_confidence * 0.7) + (float(idea.reward_score or 0) * 0.3)))

        priority = 99
        if final_confidence >= 0.85:
            priority = 1
        elif final_confidence >= 0.75:
            priority = 2
        elif final_confidence >= 0.65:
            priority = 3

        return ConfidenceAssessment.objects.update_or_create(
            idea=idea,
            defaults={
                "raw_confidence": raw,
                "regime_adjustment": round(regime_adj, 4),
                "learning_adjustment": round(learning_adj, 4),
                "risk_adjustment": round(risk_adj, 4),
                "final_confidence": round(final_confidence, 4),
                "sizing_score": round(sizing_score, 4),
                "execution_priority": priority,
                "payload": {
                    "regime": getattr(regime_state, "regime", None),
                    "risk_status": getattr(risk_state, "status", None),
                    "learning_multiplier": getattr(learning_snapshot, "confidence_multiplier", None),
                },
            }
        )[0]