from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from strategies.models import Signal, Strategy, StrategyDeployment


class StrategyDeploymentError(ValueError):
    pass


class StrategyDeploymentService:
    @staticmethod
    def _message(exc: ValidationError) -> str:
        if hasattr(exc, "message_dict"):
            return " ".join(
                message
                for messages in exc.message_dict.values()
                for message in messages
            )
        return " ".join(exc.messages)

    @classmethod
    @transaction.atomic
    def activate(
        cls,
        *,
        strategy: Strategy,
        user,
        portfolio,
        auto_execute: bool = False,
    ) -> StrategyDeployment:
        strategy = Strategy.objects.select_for_update().get(pk=strategy.pk)
        portfolio = (
            portfolio.__class__.objects
            .select_related("broker_account")
            .select_for_update()
            .get(pk=portfolio.pk)
        )
        broker_account = portfolio.broker_account

        if strategy.owner_id and strategy.owner_id != user.id:
            raise StrategyDeploymentError("Cette stratégie appartient à un autre utilisateur.")
        if portfolio.user_id != user.id or broker_account.user_id != user.id:
            raise StrategyDeploymentError("Le portefeuille ou le broker n'appartient pas à l'utilisateur.")

        deployment, _ = StrategyDeployment.objects.select_for_update().get_or_create(
            strategy=strategy,
            user=user,
            portfolio=portfolio,
            defaults={
                "broker_account": broker_account,
                "execution_mode": broker_account.mode,
                "status": "DRAFT",
            },
        )
        if deployment.status == "REVOKED":
            raise StrategyDeploymentError("Ce déploiement a été révoqué et ne peut pas être réactivé.")

        now = timezone.now()
        StrategyDeployment.objects.filter(
            strategy=strategy,
            user=user,
            status="ACTIVE",
        ).exclude(pk=deployment.pk).update(
            status="PAUSED",
            paused_at=now,
            updated_at=now,
        )

        deployment.broker_account = broker_account
        deployment.execution_mode = broker_account.mode
        deployment.status = "ACTIVE"
        deployment.auto_execute = bool(auto_execute)
        deployment.activated_by = user
        deployment.activated_at = now
        deployment.paused_at = None
        deployment.last_error = ""
        try:
            deployment.save()
        except ValidationError as exc:
            raise StrategyDeploymentError(cls._message(exc)) from exc
        return deployment

    @classmethod
    @transaction.atomic
    def pause(cls, *, deployment_id: int, user) -> StrategyDeployment:
        deployment = (
            StrategyDeployment.objects.owned_by(user)
            .select_for_update()
            .filter(pk=deployment_id)
            .first()
        )
        if deployment is None:
            raise StrategyDeploymentError("Déploiement introuvable.")
        if deployment.status == "REVOKED":
            raise StrategyDeploymentError("Un déploiement révoqué ne peut pas être modifié.")

        deployment.status = "PAUSED"
        deployment.auto_execute = False
        deployment.paused_at = timezone.now()
        deployment.save(update_fields=[
            "status",
            "auto_execute",
            "paused_at",
            "updated_at",
        ])
        return deployment

    @classmethod
    def resolve_for_order(
        cls,
        *,
        signal: Signal | None,
        user,
        portfolio,
        broker_account,
        deployment: StrategyDeployment | None = None,
    ) -> StrategyDeployment | None:
        strategy = signal.strategy if signal is not None else None
        requires_deployment = bool(strategy and strategy.status == "LIVE")

        if strategy is not None and broker_account.mode == "LIVE" and not requires_deployment:
            raise StrategyDeploymentError(
                "Une stratégie qui n'est pas en statut Live ne peut pas envoyer un ordre Live."
            )

        if deployment is not None:
            deployment = (
                StrategyDeployment.objects.select_related(
                    "strategy",
                    "user",
                    "portfolio",
                    "broker_account",
                    "strategy_version",
                )
                .filter(pk=deployment.pk)
                .first()
            )
            if deployment is None:
                raise StrategyDeploymentError("Le déploiement de stratégie n'existe plus.")

        if deployment is None and requires_deployment:
            deployment = (
                StrategyDeployment.objects.active()
                .select_related(
                    "strategy",
                    "user",
                    "portfolio",
                    "broker_account",
                    "strategy_version",
                )
                .filter(
                    strategy=strategy,
                    user=user,
                    portfolio=portfolio,
                    broker_account=broker_account,
                    execution_mode="LIVE",
                )
                .first()
            )

        if deployment is None and requires_deployment:
            raise StrategyDeploymentError(
                "Aucun déploiement Live actif ne correspond à cette stratégie, ce portefeuille et ce broker."
            )
        if deployment is None:
            return None
        if deployment.status != "ACTIVE":
            raise StrategyDeploymentError("Le déploiement de stratégie n'est pas actif.")
        if deployment.user_id != user.id:
            raise StrategyDeploymentError("Le déploiement n'appartient pas à l'utilisateur.")
        if deployment.portfolio_id != portfolio.id:
            raise StrategyDeploymentError("Le déploiement ne correspond pas au portefeuille.")
        if deployment.broker_account_id != broker_account.id:
            raise StrategyDeploymentError("Le déploiement ne correspond pas au broker.")
        if strategy is not None and deployment.strategy_id != strategy.id:
            raise StrategyDeploymentError("Le déploiement ne correspond pas à la stratégie du signal.")
        if requires_deployment and deployment.execution_mode != "LIVE":
            raise StrategyDeploymentError("Une stratégie Live exige un déploiement Live.")
        if (
            strategy is not None
            and strategy.status == "PAPER"
            and deployment.execution_mode != "PAPER"
        ):
            raise StrategyDeploymentError("Une stratégie Paper exige un déploiement Paper.")
        try:
            deployment.full_clean()
        except ValidationError as exc:
            raise StrategyDeploymentError(cls._message(exc)) from exc
        return deployment

    @staticmethod
    def active_for(*, strategy: Strategy, user) -> StrategyDeployment | None:
        return (
            StrategyDeployment.objects.active()
            .select_related("portfolio", "broker_account", "strategy")
            .filter(strategy=strategy, user=user)
            .first()
        )
