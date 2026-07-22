from __future__ import annotations

import time
from django.utils import timezone

from strategies.models import Strategy, StrategyDeployment, StrategyRun
from .signal_engine import SignalEngineService


class StrategyRunnerService:
    @staticmethod
    def run_one(strategy: Strategy, *, deployment=None) -> StrategyRun:
        if deployment is not None and deployment.strategy_id != strategy.id:
            raise ValueError("Le déploiement ne correspond pas à la stratégie.")
        run = StrategyRun.objects.create(
            strategy=strategy,
            deployment=deployment,
            run_started_at=timezone.now(),
            status="RUNNING",
            input_snapshot={
                "strategy_id": strategy.id,
                "strategy_name": strategy.name,
                "asset": strategy.asset.symbol,
                "timeframe": strategy.timeframe.code,
                "status": strategy.status,
                "autonomous": strategy.is_autonomous,
                "deployment_id": getattr(deployment, "id", None),
                "deployment_mode": getattr(deployment, "execution_mode", None),
                "portfolio_id": getattr(deployment, "portfolio_id", None),
                "broker_account_id": getattr(deployment, "broker_account_id", None),
            },
        )

        start = time.perf_counter()

        try:
            signal = SignalEngineService.evaluate_and_route(
                strategy,
                deployment=deployment,
            )

            runtime_ms = int((time.perf_counter() - start) * 1000)

            run.status = "SUCCEEDED"
            run.candle_time = signal.candle_time
            run.run_finished_at = timezone.now()
            run.runtime_ms = runtime_ms
            run.output_snapshot = {
                "signal_id": signal.id,
                "signal_side": signal.side,
                "signal_status": signal.status,
                "confidence": signal.confidence,
            }
            run.save(update_fields=[
                "status",
                "candle_time",
                "run_finished_at",
                "runtime_ms",
                "output_snapshot",
                "updated_at",
            ])

            strategy.last_run_at = timezone.now()
            strategy.last_error = ""
            strategy.save(update_fields=["last_run_at", "last_error", "updated_at"])

            signal.strategy_run = run
            signal.save(update_fields=["strategy_run", "updated_at"])

            return run

        except Exception as exc:
            runtime_ms = int((time.perf_counter() - start) * 1000)
            run.status = "FAILED"
            run.run_finished_at = timezone.now()
            run.runtime_ms = runtime_ms
            run.error_message = str(exc)
            run.save(update_fields=[
                "status",
                "run_finished_at",
                "runtime_ms",
                "error_message",
                "updated_at",
            ])

            strategy.last_run_at = timezone.now()
            strategy.last_error = str(exc)
            strategy.save(update_fields=["last_run_at", "last_error", "updated_at"])

            return run

    @staticmethod
    def run_all_autonomous() -> list[StrategyRun]:
        strategies = (
            Strategy.objects
            .filter(is_active=True, is_autonomous=True)
            .exclude(status__in=["PAUSED", "ARCHIVED", "FAILED"])
            .select_related("asset", "timeframe")
        )

        runs = []
        for strategy in strategies:
            deployments = list(
                StrategyDeployment.objects.active()
                .filter(strategy=strategy)
                .select_related("user", "portfolio", "broker_account")
            )
            if strategy.status == "LIVE":
                deployments = [
                    deployment
                    for deployment in deployments
                    if deployment.execution_mode == "LIVE"
                ]
            elif strategy.status == "PAPER":
                deployments = [
                    deployment
                    for deployment in deployments
                    if deployment.execution_mode == "PAPER"
                ]
            else:
                deployments = []
            if strategy.owner_id:
                deployments = [
                    deployment
                    for deployment in deployments
                    if deployment.user_id == strategy.owner_id
                ]

            if deployments:
                runs.extend(
                    StrategyRunnerService.run_one(
                        strategy,
                        deployment=deployment,
                    )
                    for deployment in deployments
                )
            elif strategy.status == "LIVE":
                runs.append(
                    StrategyRun.objects.create(
                        strategy=strategy,
                        run_started_at=timezone.now(),
                        run_finished_at=timezone.now(),
                        status="SKIPPED",
                        error_message="Aucun déploiement Live actif.",
                        input_snapshot={"strategy_id": strategy.id},
                    )
                )
            else:
                runs.append(StrategyRunnerService.run_one(strategy))
        return runs
