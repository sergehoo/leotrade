from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from market.models import Asset, Timeframe
from portfolio.models import Position
from strategies.models import Strategy, Signal
from strategies.services.deployment import StrategyDeploymentService
from trading.models import (
    TradingIntent,
    TradingIntentEvent,
)
from trading.services.execution.canonical_signal import CanonicalSignalExecutionService


class ExecutionService:
    def __init__(self, broker_account, portfolio):
        self.broker_account = broker_account
        self.portfolio = portfolio

    def execute_signal(
        self,
        signal: Signal,
        approved_quantity: Decimal,
        intent: TradingIntent | None = None,
    ):
        return CanonicalSignalExecutionService(
            self.broker_account,
            self.portfolio,
        ).execute(
            signal=signal,
            approved_quantity=approved_quantity,
            intent=intent,
        )


class AIPlanningService:
    @staticmethod
    def build_plan(intent: TradingIntent):
        requested = intent.target_return_percent
        duration = intent.duration_days

        feasibility = "HIGH"
        score = 0.85
        recommended_target = requested

        if requested >= 200 and duration <= 4:
            feasibility = "VERY_LOW"
            score = 0.10
            recommended_target = 10 if intent.risk_level in ["LOW", "MEDIUM"] else 25

        asset_universe = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        if intent.allowed_asset_classes:
            if "CRYPTO" not in intent.allowed_asset_classes:
                asset_universe = ["EURUSD", "XAUUSD"]

        plan = {
            "strategy_type": "HYBRID",
            "asset_universe": asset_universe,
            "timeframe": "15m" if intent.risk_level in ["HIGH", "AGGRESSIVE"] else "1h",
            "risk_per_trade_percent": (
                1.0 if intent.risk_level == "LOW"
                else 2.0 if intent.risk_level in ["MEDIUM", "HIGH"]
                else 3.0
            ),
            "max_open_positions": intent.max_open_positions or 3,
            "min_confidence_threshold": 0.70 if intent.risk_level == "LOW" else 0.75,
            "execution_mode": intent.execution_mode,
            "recommended_target_return_percent": recommended_target,
        }

        analysis = {
            "requested_return_percent": requested,
            "horizon_days": duration,
            "feasibility": feasibility,
            "feasibility_score": score,
            "recommended_mode": "PAPER" if feasibility == "VERY_LOW" else intent.execution_mode,
            "notes": [
                "L’objectif demandé est analysé automatiquement.",
                "La stratégie est ajustée au niveau de risque déclaré.",
            ],
        }

        return analysis, plan


class IntentExecutionService:
    @staticmethod
    def _resolve_asset_for_intent(intent: TradingIntent) -> Asset:
        # 1. depuis la stratégie déjà liée
        if intent.strategy_id and intent.strategy and intent.strategy.asset_id:
            return intent.strategy.asset

        # 2. premier asset de position du portefeuille
        first_position = intent.portfolio.positions.select_related("asset").order_by("id").first()
        if first_position and first_position.asset_id:
            return first_position.asset

        # 3. si un univers est défini dans le plan, on prend le premier symbol connu
        asset_universe = (intent.ai_plan or {}).get("asset_universe") or []
        if asset_universe:
            asset = Asset.objects.filter(symbol=asset_universe[0]).first()
            if asset:
                return asset

        raise ValueError(
            "Impossible de déterminer l’asset de la stratégie. "
            "Aucun asset dans le portefeuille et aucun symbole exploitable dans le plan IA."
        )

    @staticmethod
    def _resolve_timeframe_for_intent(intent: TradingIntent) -> Timeframe:
        timeframe_code = (intent.ai_plan or {}).get("timeframe")
        if timeframe_code:
            timeframe = Timeframe.objects.filter(code=timeframe_code).first()
            if timeframe:
                return timeframe

        timeframe = Timeframe.objects.order_by("minutes").first()
        if timeframe:
            return timeframe

        raise ValueError("Aucun timeframe disponible pour créer la stratégie.")

    @staticmethod
    @transaction.atomic
    def analyze(intent: TradingIntent):
        intent.status = "ANALYZING"
        intent.save(update_fields=["status", "updated_at"])

        analysis, plan = AIPlanningService.build_plan(intent)
        intent.ai_analysis = analysis
        intent.ai_plan = plan
        intent.ai_feasibility_score = analysis.get("feasibility_score", 0.0)

        if analysis["feasibility"] == "VERY_LOW" and intent.execution_mode == "LIVE":
            intent.status = "REJECTED"
            intent.rejection_reason = "Objectif trop agressif pour exécution LIVE."
        else:
            intent.status = "PLANNED"
            intent.rejection_reason = ""

        intent.save(update_fields=[
            "ai_analysis",
            "ai_plan",
            "ai_feasibility_score",
            "status",
            "rejection_reason",
            "updated_at",
        ])

        TradingIntentEvent.objects.create(
            intent=intent,
            event_type="ANALYZED",
            title="Analyse IA terminée",
            message=f"Feasibility: {analysis['feasibility']}",
            payload={"analysis": analysis, "plan": plan},
        )
        return intent

    @staticmethod
    @transaction.atomic
    def launch(intent: TradingIntent):
        if intent.status not in ["PLANNED", "APPROVED", "RUNNING"]:
            raise ValueError("Intent non prêt pour lancement.")

        if not intent.ai_plan:
            raise ValueError("Plan IA absent.")

        if intent.portfolio.user_id != intent.user_id:
            raise ValueError("Le portefeuille n'appartient pas à l'utilisateur.")
        broker_account = intent.portfolio.broker_account
        if intent.broker_account_id and intent.broker_account_id != broker_account.id:
            raise ValueError("Le broker de l'intention ne correspond pas au portefeuille.")
        if broker_account.mode != intent.execution_mode:
            raise ValueError("Le mode de l'intention ne correspond pas au broker du portefeuille.")

        strategy = intent.strategy
        if not strategy:
            asset = IntentExecutionService._resolve_asset_for_intent(intent)
            timeframe = IntentExecutionService._resolve_timeframe_for_intent(intent)

            strategy = Strategy.objects.create(
                name=f"{intent.title} Strategy",
                owner=intent.user,
                strategy_type=intent.ai_plan.get("strategy_type", "HYBRID"),
                status="PAPER",
                asset=asset,
                timeframe=timeframe,
                is_active=True,
                is_autonomous=True,
                allow_live_execution=intent.execution_mode == "LIVE",
                min_confidence_threshold=float(intent.ai_plan.get("min_confidence_threshold", 0.7)),
                risk_per_trade_percent=float(intent.ai_plan.get("risk_per_trade_percent", 2.0)),
                parameters=intent.ai_plan,
                description=f"Stratégie générée automatiquement pour l’intention {intent.title}",
            )
            intent.strategy = strategy

        if strategy.owner_id != intent.user_id:
            raise ValueError("La stratégie de l'intention n'appartient pas à l'utilisateur.")

        strategy.is_active = True
        strategy.allow_live_execution = intent.execution_mode == "LIVE"
        strategy.save(update_fields=[
            "is_active",
            "allow_live_execution",
            "updated_at",
        ])
        deployment = StrategyDeploymentService.activate(
            strategy=strategy,
            user=intent.user,
            portfolio=intent.portfolio,
            auto_execute=False,
        )
        strategy.status = intent.execution_mode
        strategy.save(update_fields=["status", "updated_at"])

        intent.status = "RUNNING"
        intent.broker_account = broker_account
        intent.approved_by_user = True
        intent.started_at = timezone.now()
        intent.expires_at = timezone.now() + timezone.timedelta(days=intent.duration_days)
        intent.save(update_fields=[
            "strategy",
            "broker_account",
            "approved_by_user",
            "status",
            "started_at",
            "expires_at",
            "updated_at",
        ])

        TradingIntentEvent.objects.create(
            intent=intent,
            event_type="STARTED",
            title="Intent lancé",
            message="La mission de trading a démarré.",
            payload={
                "strategy_id": intent.strategy_id,
                "strategy_deployment_id": deployment.id,
            },
        )
        return intent


class IntentMonitoringService:
    @staticmethod
    def refresh_metrics(intent: TradingIntent):
        # Ici on garde la logique portefeuille globale,
        # mais elle peut être affinée plus tard vers les seules positions liées à l’intention.
        positions = Position.objects.filter(
            portfolio=intent.portfolio,
            status="OPEN",
        )

        unrealized = sum((p.pnl or Decimal("0")) for p in positions)
        realized = Decimal("0")

        intent.unrealized_pnl = unrealized
        intent.realized_pnl = realized

        if intent.capital_amount and intent.capital_amount > 0:
            intent.actual_return_percent = float(((realized + unrealized) / intent.capital_amount) * 100)

        if intent.expires_at and timezone.now() >= intent.expires_at and intent.status == "RUNNING":
            intent.status = "COMPLETED"
            intent.ended_at = timezone.now()

        intent.save(update_fields=[
            "unrealized_pnl",
            "realized_pnl",
            "actual_return_percent",
            "status",
            "ended_at",
            "updated_at",
        ])
        return intent
