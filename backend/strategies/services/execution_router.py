from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from strategies.models import Signal
from strategies.services.deployment import (
    StrategyDeploymentError,
    StrategyDeploymentService,
)


class StrategyExecutionRouter:
    @staticmethod
    def route(signal: Signal, *, deployment=None) -> tuple[bool, str]:
        strategy = signal.strategy

        if not signal.user_id and not strategy.owner_id:
            signal.status = "SCORED"
            signal.save(update_fields=["status", "updated_at"])
            return True, "Opportunité système publiée en lecture seule."

        if strategy.status != "LIVE":
            if (
                strategy.status == "PAPER"
                and deployment
                and deployment.execution_mode == "PAPER"
                and deployment.auto_execute
                and strategy.is_autonomous
            ):
                signal.status = "QUEUED"
                signal.model_output = {
                    **(signal.model_output or {}),
                    "strategy_deployment_id": deployment.id,
                    "routing": "AUTO_EXECUTION_QUEUED",
                }
                signal.save(update_fields=["status", "model_output", "updated_at"])
                transaction.on_commit(
                    lambda: StrategyExecutionRouter._enqueue(signal.id, deployment.id)
                )
                return True, "Signal Paper routé vers l'auto-exécution."

            signal.status = "APPROVED"
            signal.approved_at = timezone.now()
            signal.reviewed_at = signal.approved_at
            signal.save(
                update_fields=["status", "approved_at", "reviewed_at", "updated_at"]
            )
            return True, "Signal approuvé en mode non-live."

        if deployment is None and signal.user_id:
            deployment = StrategyDeploymentService.active_for(
                strategy=strategy,
                user=signal.user,
            )
        try:
            if deployment is None:
                raise StrategyDeploymentError("Aucun déploiement Live actif.")
            StrategyDeploymentService.resolve_for_order(
                signal=signal,
                user=signal.user,
                portfolio=deployment.portfolio,
                broker_account=deployment.broker_account,
                deployment=deployment,
            )
        except StrategyDeploymentError as exc:
            signal.status = "SCORED"
            signal.model_output = {
                **(signal.model_output or {}),
                "routing": "BLOCKED_NO_DEPLOYMENT",
                "routing_error": str(exc),
            }
            signal.save(update_fields=["status", "model_output", "updated_at"])
            return False, str(exc)

        signal.model_output = {
            **(signal.model_output or {}),
            "strategy_deployment_id": deployment.id,
        }
        if deployment.auto_execute and strategy.is_autonomous:
            signal.status = "QUEUED"
            signal.model_output["routing"] = "AUTO_EXECUTION_QUEUED"
            signal.save(update_fields=["status", "model_output", "updated_at"])
            transaction.on_commit(
                lambda: StrategyExecutionRouter._enqueue(signal.id, deployment.id)
            )
            return True, "Signal routé vers l'auto-exécution Live."

        signal.status = "SCORED"
        signal.model_output["routing"] = "USER_APPROVAL_REQUIRED"
        signal.save(update_fields=["status", "model_output", "updated_at"])
        return True, "Signal Live en attente de validation utilisateur."

    @staticmethod
    def _enqueue(signal_id: int, deployment_id: int) -> None:
        from strategies.tasks import execute_deployed_signal_task

        execute_deployed_signal_task.delay(signal_id, deployment_id)
