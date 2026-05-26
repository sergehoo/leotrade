"""
leo_backtesting/tasks.py
========================

Tâches Celery pour exécuter les backtests de manière asynchrone, sans bloquer
la requête HTTP.

Le run BacktestRun est créé par la vue avec status=PENDING. La tâche le
récupère, le passe en RUNNING, exécute, puis le marque DONE / FAILED.

Robustesse :
  - try/except global pour ne jamais retry à l'infini
  - update_fields ciblé pour éviter les races
  - log structuré (run_id, strategy_id, status)
  - broadcast notification utilisateur si possible (best-effort)
"""

from __future__ import annotations

import logging
from decimal import Decimal

from celery import shared_task
from django.utils import timezone


log = logging.getLogger("leotrade.backtesting.tasks")


@shared_task(name="leo_backtesting.tasks.run_backtest_task", bind=True)
def run_backtest_task(self, backtest_run_id: int):
    """
    Charge le BacktestRun, exécute le backtest, met à jour le statut.
    Idempotent : si le run est déjà DONE/FAILED, on ne ré-exécute pas.
    """
    from leo_backtesting.models import BacktestRun
    from leo_backtesting.services import run_backtest

    bt = BacktestRun.objects.filter(pk=backtest_run_id).first()
    if not bt:
        log.warning("run_backtest_task.not_found id=%s", backtest_run_id)
        return {"ok": False, "err": "not_found"}

    if bt.status not in ("PENDING", "RUNNING"):
        log.info(
            "run_backtest_task.skipped id=%s status=%s",
            backtest_run_id, bt.status,
        )
        return {"ok": True, "skipped": True, "status": bt.status}

    bt.status = "RUNNING"
    bt.save(update_fields=["status", "updated_at"])

    log.info(
        "run_backtest_task.start id=%s strategy=%s",
        backtest_run_id, bt.strategy_id,
    )

    try:
        # Le service `run_backtest` crée son propre BacktestRun.
        # On va plutôt l'exécuter et copier le résultat dans notre `bt` existant
        # pour ne pas avoir deux records en base.
        produced = run_backtest(bt.strategy)

        if produced and produced.id != bt.id:
            bt.status = produced.status
            bt.metrics = produced.metrics or {}
            bt.equity_curve = produced.equity_curve or []
            bt.trades_log = produced.trades_log or []
            bt.start_date = produced.start_date or bt.start_date
            bt.end_date = produced.end_date or bt.end_date
            bt.initial_cash = produced.initial_cash
            bt.commission = produced.commission
            bt.save()
            try:
                produced.delete()
            except Exception:
                pass
        elif produced and produced.id == bt.id:
            # Cas idéal : run_backtest a réutilisé notre objet
            pass

        log.info(
            "run_backtest_task.done id=%s status=%s",
            backtest_run_id, bt.status,
        )

        # Notification utilisateur best-effort
        _notify_user_backtest_done(bt)

        return {"ok": True, "id": backtest_run_id, "status": bt.status}

    except Exception as exc:
        log.exception(
            "run_backtest_task.failed id=%s strategy=%s err=%s",
            backtest_run_id, bt.strategy_id, exc,
        )
        bt.status = "FAILED"
        bt.metrics = {"error": str(exc)[:500]}
        bt.save(update_fields=["status", "metrics", "updated_at"])
        _notify_user_backtest_failed(bt, str(exc)[:200])
        return {"ok": False, "id": backtest_run_id, "err": str(exc)[:200]}


def _notify_user_backtest_done(bt) -> None:
    """
    Pousse une notification temps réel à l'utilisateur via Channels (best-effort).
    """
    try:
        from core.realtime import RealtimeBroadcastService
        user_id = _resolve_user_id(bt)
        if user_id is None:
            return
        RealtimeBroadcastService.broadcast_notification(
            user_id=user_id,
            payload={
                "kind": "backtest_done",
                "level": "success",
                "message": f"Backtest #{bt.id} terminé : {bt.name}",
                "backtest_id": bt.id,
            },
        )
    except Exception:
        pass  # noqa


def _notify_user_backtest_failed(bt, reason: str) -> None:
    try:
        from core.realtime import RealtimeBroadcastService
        user_id = _resolve_user_id(bt)
        if user_id is None:
            return
        RealtimeBroadcastService.broadcast_notification(
            user_id=user_id,
            payload={
                "kind": "backtest_failed",
                "level": "error",
                "message": f"Échec backtest #{bt.id} : {reason}",
                "backtest_id": bt.id,
            },
        )
    except Exception:
        pass


def _resolve_user_id(bt) -> int | None:
    strategy = getattr(bt, "strategy", None)
    if not strategy:
        return None
    if getattr(strategy, "user_id", None):
        return strategy.user_id
    pf = getattr(strategy, "portfolio", None)
    if pf and getattr(pf, "user_id", None):
        return pf.user_id
    return None
