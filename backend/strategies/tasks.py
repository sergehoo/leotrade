# strategies/tasks.py
from __future__ import annotations

import logging
from decimal import Decimal

from celery import shared_task

from strategies.services.strategy_runner import StrategyRunnerService

logger = logging.getLogger(__name__)


def _strategy_stake(strategy, portfolio) -> Decimal:
    equity = Decimal(str(portfolio.equity or portfolio.current_balance or "0"))
    available = Decimal(str(portfolio.available_cash or "0"))
    risk_percent = Decimal(str(strategy.risk_per_trade_percent or "0"))
    requested = equity * risk_percent / Decimal("100")
    if strategy.max_position_size and strategy.max_position_size > 0:
        requested = min(requested, strategy.max_position_size)
    if available > 0:
        requested = min(requested, available)
    return max(requested.quantize(Decimal("0.01")), Decimal("0.01"))


@shared_task(name="strategies.tasks.execute_deployed_signal_task")
def execute_deployed_signal_task(signal_id: int, deployment_id: int):
    from execution.intents import OrderIntent
    from execution.services import ExecutionOrchestrator
    from strategies.models import Signal, StrategyDeployment
    from strategies.services.deployment import StrategyDeploymentService

    signal = (
        Signal.objects.select_related("strategy", "strategy__asset", "user")
        .filter(pk=signal_id)
        .first()
    )
    deployment = (
        StrategyDeployment.objects.select_related(
            "strategy",
            "user",
            "portfolio",
            "broker_account",
        )
        .filter(pk=deployment_id)
        .first()
    )
    if signal is None or deployment is None:
        return {"ok": False, "reason": "signal_or_deployment_missing"}
    if signal.status != "QUEUED":
        return {"ok": True, "skipped": True, "status": signal.status}

    try:
        StrategyDeploymentService.resolve_for_order(
            signal=signal,
            user=deployment.user,
            portfolio=deployment.portfolio,
            broker_account=deployment.broker_account,
            deployment=deployment,
        )
        order = ExecutionOrchestrator.submit(
            OrderIntent(
                user_id=deployment.user_id,
                portfolio_id=deployment.portfolio_id,
                broker_account_id=deployment.broker_account_id,
                strategy_deployment_id=deployment.id,
                symbol=signal.strategy.asset.symbol,
                side=signal.side,
                requested_stake_amount=_strategy_stake(
                    signal.strategy,
                    deployment.portfolio,
                ),
                requested_price=signal.price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                mode=deployment.execution_mode,
                source="STRATEGY",
                asset_id=signal.strategy.asset_id,
                signal_id=signal.id,
                idempotency_key=f"strategy-deployment:{deployment.id}:signal:{signal.id}",
                metadata={
                    "confidence": signal.confidence,
                    "strategy_id": signal.strategy_id,
                    "strategy_deployment_id": deployment.id,
                },
            )
        )
    except Exception as exc:
        signal.status = "FAILED"
        signal.model_output = {
            **(signal.model_output or {}),
            "auto_execution_error": str(exc),
        }
        signal.save(update_fields=["status", "model_output", "updated_at"])
        logger.exception(
            "strategy_signal_auto_execution_failed signal_id=%s deployment_id=%s",
            signal_id,
            deployment_id,
        )
        return {"ok": False, "reason": str(exc)}

    signal.model_output = {
        **(signal.model_output or {}),
        "execution_order_id": order.id,
        "strategy_deployment_id": deployment.id,
    }
    signal.save(update_fields=["model_output", "updated_at"])
    return {"ok": True, "order_id": order.id, "status": order.status}


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
