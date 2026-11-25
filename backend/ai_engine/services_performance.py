"""
Score de performance IA + comparaison prévision/réalité.

Deux services :

1. AIPerformanceService — agrège la boucle complète
   AIDecisionLog (décision IA) → TradeIdeaFeedback (résultat réel)
   pour produire : taux de réussite, calibration de la confiance,
   répartition par provider, historique des recommandations.

2. PredictionEvaluationService — évalue chaque StrategyPrediction
   contre la bougie suivante réelle (UP/DOWN) et persiste
   actual_label / is_correct pour le suivi prévision vs réalité.

Aucune donnée simulée : tout est calculé depuis la base réelle ; les
sections sans données renvoient des compteurs à zéro avec sample_size=0.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import Avg, Count, Q
from django.utils import timezone

log = logging.getLogger("lyneci.ai.performance")

# Décisions IA considérées comme "engagées" (l'IA a pris position)
ACTIONABLE_DECISIONS = ("EXECUTE", "PLAN")
WIN_OUTCOMES = ("WIN",)
LOSS_OUTCOMES = ("LOSS",)
CLOSED_OUTCOMES = ("WIN", "LOSS", "BREAKEVEN")


class AIPerformanceService:
    @classmethod
    def summary(cls, user=None, days: int = 30) -> dict:
        """Score de performance IA sur la période, basé sur les résultats réels."""
        from ai_engine.models import AIDecisionLog
        from trading.models import TradeIdeaFeedback

        since = timezone.now() - timedelta(days=days)

        logs = AIDecisionLog.objects.filter(created_at__gte=since)
        if user is not None:
            logs = logs.filter(user=user)

        decision_counts = dict(
            logs.values_list("decision").annotate(n=Count("id"))
        )

        # Boucle fermée : décisions actionnables dont l'idée a un résultat réel
        feedbacks = TradeIdeaFeedback.objects.filter(
            idea__ai_decisions__in=logs.filter(decision__in=ACTIONABLE_DECISIONS),
            outcome__in=CLOSED_OUTCOMES,
        ).distinct()

        wins = feedbacks.filter(outcome__in=WIN_OUTCOMES).count()
        losses = feedbacks.filter(outcome__in=LOSS_OUTCOMES).count()
        closed = feedbacks.count()
        hit_rate = (wins / closed) if closed else None

        # Calibration : confiance moyenne des décisions gagnantes vs perdantes.
        # Une IA bien calibrée a une confiance plus haute sur ses gains.
        conf_win = logs.filter(
            decision__in=ACTIONABLE_DECISIONS,
            trade_idea__feedback__outcome__in=WIN_OUTCOMES,
        ).aggregate(v=Avg("confidence"))["v"]
        conf_loss = logs.filter(
            decision__in=ACTIONABLE_DECISIONS,
            trade_idea__feedback__outcome__in=LOSS_OUTCOMES,
        ).aggregate(v=Avg("confidence"))["v"]

        per_provider = list(
            logs.values("provider").annotate(
                calls=Count("id"),
                avg_confidence=Avg("confidence"),
                fallbacks=Count("id", filter=Q(fallback_used=True)),
            ).order_by("-calls")
        )

        # Score global 0-100 : hit rate (60 pts) + calibration (25 pts)
        # + taux de complétion sans fallback (15 pts). None si aucun échantillon.
        score = None
        if closed:
            score = (hit_rate or 0) * 60
            if conf_win is not None and conf_loss is not None:
                score += 25 if conf_win > conf_loss else 10
            total_calls = sum(p["calls"] for p in per_provider) or 1
            fallback_calls = sum(p["fallbacks"] for p in per_provider)
            score += (1 - fallback_calls / total_calls) * 15
            score = round(min(score, 100), 1)

        return {
            "period_days": days,
            "sample_size": closed,
            "wins": wins,
            "losses": losses,
            "hit_rate": round(hit_rate, 4) if hit_rate is not None else None,
            "avg_confidence_on_wins": round(conf_win, 4) if conf_win is not None else None,
            "avg_confidence_on_losses": round(conf_loss, 4) if conf_loss is not None else None,
            "well_calibrated": (
                conf_win > conf_loss
                if conf_win is not None and conf_loss is not None
                else None
            ),
            "decision_counts": decision_counts,
            "per_provider": per_provider,
            "ai_score": score,
        }

    @classmethod
    def recommendation_history(cls, user=None, limit: int = 30) -> list[dict]:
        """Historique des décisions IA avec leur résultat réel (quand connu)."""
        from ai_engine.models import AIDecisionLog

        logs = (
            AIDecisionLog.objects
            .filter(decision__in=ACTIONABLE_DECISIONS)
            .select_related("trade_idea", "trade_idea__feedback")
            .order_by("-created_at")
        )
        if user is not None:
            logs = logs.filter(user=user)

        history = []
        for entry in logs[:limit]:
            feedback = getattr(entry.trade_idea, "feedback", None) if entry.trade_idea_id else None
            history.append({
                "id": entry.id,
                "created_at": entry.created_at.isoformat(),
                "symbol": entry.symbol,
                "provider": entry.provider,
                "decision": entry.decision,
                "confidence": entry.confidence,
                "rationale": entry.rationale[:280],
                "analysis": entry.analysis or {},
                "outcome": getattr(feedback, "outcome", None),
                "pnl_amount": (
                    float(feedback.pnl_amount)
                    if feedback is not None and feedback.pnl_amount is not None
                    else None
                ),
            })
        return history


class PredictionEvaluationService:
    """Compare chaque StrategyPrediction à la bougie réelle suivante."""

    # Labels reconnus → direction attendue
    UP_LABELS = {"UP", "BUY", "LONG", "BULLISH", "CALL"}
    DOWN_LABELS = {"DOWN", "SELL", "SHORT", "BEARISH", "PUT"}

    @classmethod
    def evaluate_pending(cls, limit: int = 500) -> dict:
        """Évalue les prédictions non encore confrontées à la réalité."""
        from market.models import Candle
        from strategies.models import StrategyPrediction

        pending = (
            StrategyPrediction.objects
            .filter(is_correct__isnull=True)
            .exclude(predicted_label="")
            .select_related("strategy", "strategy__asset", "strategy__timeframe")
            .order_by("candle_time")[:limit]
        )

        evaluated = correct = 0
        for prediction in pending:
            strategy = prediction.strategy
            if not strategy.asset_id or not strategy.timeframe_id:
                continue

            # Bougie strictement postérieure à la prédiction (la réalité)
            next_candle = (
                Candle.objects
                .filter(
                    asset_id=strategy.asset_id,
                    timeframe_id=strategy.timeframe_id,
                    open_time__gt=prediction.candle_time,
                )
                .order_by("open_time")
                .first()
            )
            if next_candle is None:
                continue  # réalité pas encore connue — on réessaiera

            if next_candle.close > next_candle.open:
                actual = "UP"
            elif next_candle.close < next_candle.open:
                actual = "DOWN"
            else:
                actual = "FLAT"

            label = (prediction.predicted_label or "").upper()
            if label in cls.UP_LABELS:
                is_correct = actual == "UP"
            elif label in cls.DOWN_LABELS:
                is_correct = actual == "DOWN"
            else:
                # Label non directionnel (ex. "NEUTRAL") : correct si flat
                is_correct = actual == "FLAT"

            prediction.actual_label = actual
            prediction.is_correct = is_correct
            prediction.evaluated_at = timezone.now()
            prediction.save(update_fields=["actual_label", "is_correct", "evaluated_at"])

            evaluated += 1
            if is_correct:
                correct += 1

        log.info("predictions.evaluated count=%s correct=%s", evaluated, correct)
        return {"evaluated": evaluated, "correct": correct}

    @classmethod
    def accuracy(cls, strategy=None, days: int = 30) -> dict:
        """Taux de réussite des prédictions évaluées (réel uniquement)."""
        from strategies.models import StrategyPrediction

        since = timezone.now() - timedelta(days=days)
        qs = StrategyPrediction.objects.filter(
            is_correct__isnull=False, candle_time__gte=since
        )
        if strategy is not None:
            qs = qs.filter(strategy=strategy)

        total = qs.count()
        correct = qs.filter(is_correct=True).count()
        return {
            "period_days": days,
            "sample_size": total,
            "correct": correct,
            "accuracy": round(correct / total, 4) if total else None,
        }
