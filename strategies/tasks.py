# strategies/tasks.py
from __future__ import annotations

import logging

from celery import shared_task

from strategies.services.strategy_runner import StrategyRunnerService

logger = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def run_all_autonomous_strategies_task(self):
    """
    Exécute toutes les stratégies autonomes actives.
    Retourne un résumé sérialisable pour inspection dans Celery.
    """
    runs = StrategyRunnerService.run_all_autonomous()

    payload = {
        "total": len(runs),
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
        "runs": [],
    }

    for run in runs:
        if run.status == "SUCCEEDED":
            payload["succeeded"] += 1
        elif run.status == "SKIPPED":
            payload["skipped"] += 1
        else:
            payload["failed"] += 1

        payload["runs"].append({
            "run_id": run.id,
            "strategy_id": run.strategy_id,
            "strategy_name": run.strategy.name,
            "status": run.status,
            "runtime_ms": run.runtime_ms,
            "started_at": run.run_started_at.isoformat() if run.run_started_at else None,
            "finished_at": run.run_finished_at.isoformat() if run.run_finished_at else None,
            "error_message": run.error_message,
        })

    logger.info("Autonomous strategies run summary: %s", payload)
    return payload