from __future__ import annotations

from decimal import Decimal
from django.db import transaction
from django.utils import timezone

from execution.notifications import TradingNotificationService
from core.realtime import RealtimeBroadcastService
# from .models_ai import TradeRecommendation, DecisionAudit
from .trade_idea_execution import TradeIdeaExecutionService
from ..models import TradeIdea
from ..models_ai import TradeRecommendation, DecisionAudit


# from .models import TradeIdea


class RecommendationActionService:
    @staticmethod
    @transaction.atomic
    def approve_by_user(recommendation: TradeRecommendation):
        recommendation.status = "APPROVED_BY_USER"
        recommendation.approved_at = timezone.now()
        recommendation.save(update_fields=["status", "approved_at", "updated_at"])

        DecisionAudit.objects.filter(recommendation=recommendation).update(
            final_decision="APPROVED_BY_USER",
            updated_at=timezone.now(),
        )

        TradingNotificationService.notify_success(
            user_id=recommendation.user_id,
            message=f"Recommandation approuvée sur {recommendation.opportunity.symbol}",
            payload={"recommendation_id": recommendation.id},
        )

        RealtimeBroadcastService.broadcast_dashboard_update(
            user_id=recommendation.user_id,
            payload={
                "kind": "recommendation_approved",
                "recommendation_id": recommendation.id,
                "symbol": recommendation.opportunity.symbol,
            },
        )

        return recommendation

    @staticmethod
    @transaction.atomic
    def reject_by_user(recommendation: TradeRecommendation):
        recommendation.status = "REJECTED_BY_USER"
        recommendation.save(update_fields=["status", "updated_at"])

        DecisionAudit.objects.filter(recommendation=recommendation).update(
            final_decision="REJECTED_BY_USER",
            updated_at=timezone.now(),
        )

        return recommendation

    @staticmethod
    @transaction.atomic
    def execute_recommendation(recommendation: TradeRecommendation):
        if recommendation.status not in {"APPROVED_BY_AI", "APPROVED_BY_USER", "PENDING"}:
            raise ValueError("Cette recommandation ne peut pas être exécutée.")

        opportunity = recommendation.opportunity

        trade_idea = TradeIdea.objects.create(
            user=recommendation.user,
            asset=opportunity.asset,
            symbol=opportunity.symbol,
            direction=opportunity.direction,
            entry_price=opportunity.entry_price,
            stop_loss=opportunity.stop_loss,
            take_profit=opportunity.take_profit,
            confidence_score=opportunity.confidence_score,
            setup_score=opportunity.setup_score,
            risk_score=opportunity.risk_score,
            reward_score=opportunity.reward_score,
            overall_score=opportunity.overall_score,
            explanation=opportunity.explanation,
            features_snapshot=opportunity.feature_snapshot,
            status="APPROVED",
        )

        result = TradeIdeaExecutionService.execute(
            idea=trade_idea,
            broker_account=recommendation.broker_account,
            portfolio=recommendation.portfolio,
            stake_amount=Decimal(str(recommendation.stake_amount)),
        )

        recommendation.status = "EXECUTED"
        recommendation.executed_at = timezone.now()
        recommendation.save(update_fields=["status", "executed_at", "updated_at"])

        DecisionAudit.objects.filter(recommendation=recommendation).update(
            final_decision="EXECUTED",
            execution_output={
                "trade_idea_id": trade_idea.id,
                "order_id": result["order"].id,
                "order_status": result["order"].status,
            },
            updated_at=timezone.now(),
        )

        return result