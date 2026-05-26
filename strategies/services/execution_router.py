from __future__ import annotations

from django.utils import timezone

from strategies.models import Signal


class StrategyExecutionRouter:
    @staticmethod
    def route(signal: Signal) -> tuple[bool, str]:
        strategy = signal.strategy

        if not strategy.allow_live_execution:
            signal.status = "APPROVED"
            signal.approved_at = timezone.now()
            signal.save(update_fields=["status", "approved_at", "updated_at"])
            return True, "Signal approuvé en mode non-live."

        signal.status = "QUEUED"
        signal.save(update_fields=["status", "updated_at"])
        return True, "Signal routé vers la file d'exécution."