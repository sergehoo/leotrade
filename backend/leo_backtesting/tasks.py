from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone


log = logging.getLogger("lyneci.backtesting.tasks")


@shared_task(
    name="leo_backtesting.tasks.run_backtest_task",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_backtest_task(self, backtest_run_id: int):
    from leo_backtesting.models import BacktestRun
    from leo_backtesting.services import (
        claim_backtest_run,
        mark_backtest_failed,
        run_backtest,
    )

    worker_task_id = getattr(self.request, "id", None) or f"direct-{uuid.uuid4()}"
    run = claim_backtest_run(backtest_run_id, worker_task_id)
    if run is None:
        existing = BacktestRun.objects.filter(pk=backtest_run_id).first()
        if existing is None:
            log.warning("backtest.run.not_found run_id=%s", backtest_run_id)
            return {"ok": False, "error": "not_found"}
        log.info(
            "backtest.run.skipped run_id=%s status=%s worker_task_id=%s",
            backtest_run_id,
            existing.status,
            worker_task_id,
        )
        return {
            "ok": existing.status == "DONE",
            "skipped": True,
            "status": existing.status,
        }

    log.info(
        "backtest.run.started run_id=%s strategy_id=%s attempt=%s worker_task_id=%s",
        run.id,
        run.strategy_id,
        run.attempt_count,
        worker_task_id,
    )

    try:
        completed = run_backtest(
            run.strategy,
            backtest_run=run,
            worker_task_id=worker_task_id,
            raise_errors=True,
        )
    except Exception as exc:
        log.exception(
            "backtest.run.failed run_id=%s strategy_id=%s worker_task_id=%s",
            run.id,
            run.strategy_id,
            worker_task_id,
        )
        failed = mark_backtest_failed(
            run.id,
            exc,
            worker_task_id=worker_task_id,
        )
        if failed is not None:
            _notify_user_backtest_failed(failed, failed.failure_message)
        return {
            "ok": False,
            "id": run.id,
            "status": failed.status if failed else "FAILED",
            "error": str(exc)[:200],
        }

    log.info(
        "backtest.run.completed run_id=%s strategy_id=%s trades=%s data_points=%s",
        completed.id,
        completed.strategy_id,
        completed.metrics.get("trades_count", 0),
        completed.data_points,
    )
    _notify_user_backtest_done(completed)
    return {"ok": True, "id": completed.id, "status": completed.status}


@shared_task(name="leo_backtesting.tasks.recover_stale_backtest_runs_task")
def recover_stale_backtest_runs_task():
    from core.outbox import OutboxService
    from leo_backtesting.event_topics import BACKTEST_RUN_REQUESTED
    from leo_backtesting.models import BacktestRun

    stale_seconds = int(getattr(settings, "BACKTEST_STALE_RUN_SECONDS", 600))
    max_attempts = int(getattr(settings, "BACKTEST_MAX_ATTEMPTS", 2))
    stale_before = timezone.now() - timedelta(seconds=stale_seconds)
    candidate_ids = list(
        BacktestRun.objects.filter(
            status="RUNNING",
            started_at__lt=stale_before,
        ).values_list("id", flat=True)[:100]
    )
    stats = {"requeued": 0, "failed": 0}

    for run_id in candidate_ids:
        failed_run = None
        with transaction.atomic():
            run = BacktestRun.objects.select_for_update().filter(pk=run_id).first()
            if (
                run is None
                or run.status != "RUNNING"
                or run.started_at is None
                or run.started_at >= stale_before
            ):
                continue

            if run.attempt_count >= max_attempts:
                run.status = "FAILED"
                run.failure_message = "Backtest interrompu après plusieurs tentatives."
                run.metrics = {"error": run.failure_message}
                run.completed_at = timezone.now()
                run.save(
                    update_fields=[
                        "status",
                        "failure_message",
                        "metrics",
                        "completed_at",
                        "updated_at",
                    ]
                )
                failed_run = run
                stats["failed"] += 1
            else:
                next_attempt = run.attempt_count + 1
                run.status = "PENDING"
                run.worker_task_id = ""
                run.started_at = None
                run.failure_message = ""
                run.save(
                    update_fields=[
                        "status",
                        "worker_task_id",
                        "started_at",
                        "failure_message",
                        "updated_at",
                    ]
                )
                OutboxService.enqueue(
                    topic=BACKTEST_RUN_REQUESTED,
                    aggregate_type="leo_backtesting.BacktestRun",
                    aggregate_id=run.id,
                    payload={"backtest_run_id": run.id},
                    idempotency_key=f"backtest:{run.id}:attempt:{next_attempt}",
                )
                stats["requeued"] += 1

        if failed_run is not None:
            _notify_user_backtest_failed(failed_run, failed_run.failure_message)

    if candidate_ids:
        log.warning("backtest.recovery completed stats=%s", stats)
    return stats


def _notify_user_backtest_done(run) -> None:
    try:
        from core.realtime import RealtimeBroadcastService

        if run.requested_by_id is None:
            return
        RealtimeBroadcastService.broadcast_notification(
            user_id=run.requested_by_id,
            payload={
                "kind": "backtest_done",
                "level": "success",
                "message": f"Backtest #{run.id} terminé : {run.name}",
                "backtest_id": run.id,
            },
        )
    except Exception:
        log.exception("backtest.notification.done_failed run_id=%s", run.id)


def _notify_user_backtest_failed(run, reason: str) -> None:
    try:
        from core.realtime import RealtimeBroadcastService

        if run.requested_by_id is None:
            return
        RealtimeBroadcastService.broadcast_notification(
            user_id=run.requested_by_id,
            payload={
                "kind": "backtest_failed",
                "level": "error",
                "message": f"Échec backtest #{run.id} : {reason[:200]}",
                "backtest_id": run.id,
            },
        )
    except Exception:
        log.exception("backtest.notification.failed_failed run_id=%s", run.id)
