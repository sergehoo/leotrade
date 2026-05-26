from __future__ import annotations

import time
from django.utils import timezone

from strategies.models import Strategy, StrategyRun
from .signal_engine import SignalEngineService


class StrategyRunnerService:
    @staticmethod
    def run_one(strategy: Strategy) -> StrategyRun:
        run = StrategyRun.objects.create(
            strategy=strategy,
            run_started_at=timezone.now(),
            status="RUNNING",
            input_snapshot={
                "strategy_id": strategy.id,
                "strategy_name": strategy.name,
                "asset": strategy.asset.symbol,
                "timeframe": strategy.timeframe.code,
                "status": strategy.status,
                "autonomous": strategy.is_autonomous,
            },
        )

        start = time.perf_counter()

        try:
            signal = SignalEngineService.evaluate_and_route(strategy)

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
            runs.append(StrategyRunnerService.run_one(strategy))
        return runs
