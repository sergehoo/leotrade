"""
ai_engine/tasks.py
==================

Tâche Celery périodique : interroge l'IA (Claude/Ollama/Heuristic) pour les
TradeIdea récentes en statut NEW/REVIEW et enregistre la décision.

Singleton lock Redis pour éviter les chevauchements.
"""

from __future__ import annotations

import logging

from celery import shared_task

from core.redis_lock import single_run


log = logging.getLogger("leotrade.ai_engine.tasks")


@shared_task(name="ai_engine.tasks.advise_open_trade_ideas_task", bind=True)
def advise_open_trade_ideas_task(self, max_ideas: int = 50):
    """
    Pour chaque TradeIdea NEW ou REVIEW sans AIDecisionLog récent, demander un avis.
    """
    from trading.models import TradeIdea
    from ai_engine.integrations import advise_for_trade_idea
    from ai_engine.models import AIDecisionLog
    from django.db.models import Exists, OuterRef

    with single_run("lock:ai_advise_trade_ideas", ttl=120) as acquired:
        if not acquired:
            log.info("advise_open_trade_ideas_task.skipped lock_held")
            return {"skipped": True}

        ideas_qs = TradeIdea.objects.filter(
            status__in=["NEW", "REVIEW"],
        ).select_related("asset", "timeframe", "portfolio").order_by("-created_at")[:max_ideas]

        n_ok, n_skipped, n_err = 0, 0, 0
        for idea in ideas_qs:
            # Skip si déjà décidé dans la dernière heure
            if AIDecisionLog.objects.filter(trade_idea=idea).exists():
                n_skipped += 1
                continue

            try:
                decision = advise_for_trade_idea(
                    idea, user=getattr(idea, "user", None),
                    portfolio=getattr(idea, "portfolio", None),
                )
                # Si EXECUTE et confidence haute, on peut tagger l'idea comme APPROVED
                if decision.decision == "EXECUTE" and decision.confidence >= 0.75:
                    idea.status = "APPROVED"
                    idea.save(update_fields=["status", "updated_at"])
                elif decision.decision == "REJECT":
                    idea.status = "REJECTED"
                    idea.save(update_fields=["status", "updated_at"])
                n_ok += 1
            except Exception as exc:
                log.exception("advise_open_trade_ideas_task.idea_failed idea_id=%s err=%s", idea.id, exc)
                n_err += 1

        log.info("advise_open_trade_ideas_task.done ok=%s skipped=%s err=%s", n_ok, n_skipped, n_err)
        return {"ok": n_ok, "skipped": n_skipped, "err": n_err}


@shared_task(name="ai_engine.tasks.evaluate_predictions_task")
def evaluate_predictions_task(limit: int = 500):
    """
    Comparaison prévision/réalité : confronte chaque StrategyPrediction
    non évaluée à la bougie réelle suivante et persiste le résultat
    (actual_label / is_correct). Alimente le score de performance IA.
    """
    from ai_engine.services_performance import PredictionEvaluationService

    result = PredictionEvaluationService.evaluate_pending(limit=limit)
    log.info(
        "evaluate_predictions_task done evaluated=%s correct=%s",
        result["evaluated"], result["correct"],
    )
    return result
