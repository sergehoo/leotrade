from __future__ import annotations

import hashlib
import json
import time
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from django.db import transaction

from brokers.models import BrokerConstraint
from brokers.services.base import BrokerConstraintSyncService
from core.realtime import RealtimeBroadcastService
from execution.notifications import TradingNotificationService
from risk.services import PositionSizingService, RiskGuardService
from trading.models_ai import (
    MarketOpportunity,
    TradeRecommendation,
    AIModelRegistry,
    AIInferenceLog,
    DecisionAudit,
)


logger = logging.getLogger(__name__)


def _d(value, default="0") -> Decimal:
    try:
        if value is None or value == "":
            return Decimal(default)
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


@dataclass
class AIRecommendationResult:
    recommendation_type: str
    ai_summary: str
    ai_confidence: Decimal
    stake_amount: Decimal
    recommended_quantity: Decimal
    recommended_notional: Decimal
    expected_risk_amount: Decimal
    expected_reward_amount: Decimal
    risk_reward_ratio: Decimal
    decision_payload: dict


class AIInferenceService:
    @staticmethod
    def get_default_model() -> Optional[AIModelRegistry]:
        return AIModelRegistry.objects.filter(is_active=True).order_by("-created_at").first()

    @staticmethod
    def hash_payload(payload: dict) -> str:
        raw = json.dumps(payload, sort_keys=True, default=str).encode()
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def run_local_inference(input_payload: dict) -> dict:
        opp = input_payload["opportunity"]
        portfolio = input_payload["portfolio"]
        risk = input_payload["risk_profile"]

        overall_score = _d(opp.get("overall_score"))
        confidence = _d(opp.get("confidence_score"))
        available_cash = _d(portfolio.get("available_cash"))
        equity = _d(portfolio.get("equity"))
        max_risk_per_trade = _d(risk.get("max_risk_per_trade"))

        if overall_score >= Decimal("0.80") and confidence >= Decimal("0.70"):
            rec_type = "EXECUTE"
            stake_pct = Decimal("0.10")
        elif overall_score >= Decimal("0.60"):
            rec_type = "PLAN"
            stake_pct = Decimal("0.05")
        else:
            rec_type = "WATCH"
            stake_pct = Decimal("0.02")

        max_risk_cash = (equity * max_risk_per_trade) / Decimal("100")
        base_stake = available_cash * stake_pct
        final_stake = min(base_stake, available_cash, max_risk_cash * Decimal("4"))

        return {
            "recommendation_type": rec_type,
            "ai_summary": (
                f"Opportunity {opp.get('symbol')} classée {rec_type} "
                f"avec score global {overall_score} et confiance {confidence}."
            ),
            "ai_confidence": str(confidence),
            "stake_amount": str(final_stake.quantize(Decimal("0.01"))),
            "decision_payload": {
                "strategy_mode": "heuristic_local",
                "stake_pct": str(stake_pct),
            }
        }

    @classmethod
    @transaction.atomic
    def infer(cls, *, user, portfolio, input_payload: dict) -> tuple[dict, AIInferenceLog]:
        model = cls.get_default_model()
        prompt_hash = cls.hash_payload(input_payload)
        started = time.perf_counter()

        success = True
        error_message = None
        output_payload = {}

        try:
            output_payload = cls.run_local_inference(input_payload)
        except Exception as exc:
            success = False
            error_message = str(exc)

        latency_ms = int((time.perf_counter() - started) * 1000)

        log = AIInferenceLog.objects.create(
            user=user,
            portfolio=portfolio,
            model=model,
            prompt_hash=prompt_hash,
            input_payload=input_payload,
            output_payload=output_payload,
            latency_ms=latency_ms,
            cost_estimate=Decimal("0.000000"),
            success=success,
            error_message=error_message,
        )

        if not success:
            raise ValueError(error_message or "Échec de l'inférence IA.")

        return output_payload, log


class AIRecommendationService:
    DEFAULT_MIN_QTY = Decimal("0.00000001")
    DEFAULT_QTY_STEP = Decimal("0.00000001")
    DEFAULT_MIN_NOTIONAL = Decimal("0")
    DEFAULT_LEVERAGE = Decimal("1")

    @classmethod
    def build_input_payload(cls, *, user, portfolio, opportunity, risk_profile) -> dict:
        open_positions_count = portfolio.positions.filter(status__in=["OPEN", "PARTIALLY_CLOSED"]).count()

        return {
            "user_id": user.id,
            "portfolio": {
                "id": portfolio.id,
                "name": portfolio.name,
                "equity": str(portfolio.equity),
                "balance": str(portfolio.current_balance),
                "available_cash": str(portfolio.available_cash),
                "locked_cash": str(portfolio.locked_cash),
                "drawdown_percent": str(portfolio.current_drawdown_percent),
                "open_positions_count": open_positions_count,
            },
            "opportunity": {
                "id": opportunity.id,
                "symbol": opportunity.symbol,
                "direction": opportunity.direction,
                "timeframe_code": opportunity.timeframe_code,
                "entry_price": str(opportunity.entry_price),
                "stop_loss": str(opportunity.stop_loss) if opportunity.stop_loss is not None else None,
                "take_profit": str(opportunity.take_profit) if opportunity.take_profit is not None else None,
                "confidence_score": str(opportunity.confidence_score),
                "setup_score": str(opportunity.setup_score),
                "risk_score": str(opportunity.risk_score),
                "reward_score": str(opportunity.reward_score),
                "overall_score": str(opportunity.overall_score),
                "regime_label": opportunity.regime_label,
                "feature_snapshot": opportunity.feature_snapshot,
            },
            "risk_profile": {
                "id": risk_profile.id,
                "max_risk_per_trade": str(risk_profile.max_risk_per_trade),
                "max_daily_loss": str(risk_profile.max_daily_loss),
                "max_weekly_loss": str(risk_profile.max_weekly_loss),
                "max_drawdown": str(risk_profile.max_drawdown),
                "max_open_positions": risk_profile.max_open_positions,
                "max_symbol_exposure_percent": str(risk_profile.max_symbol_exposure_percent),
                "max_asset_class_exposure_percent": str(risk_profile.max_asset_class_exposure_percent),
                "max_correlated_exposure_percent": str(risk_profile.max_correlated_exposure_percent),
                "min_confidence": str(risk_profile.min_confidence),
            }
        }

    @classmethod
    def _resolve_constraint(cls, broker_account, symbol: str):
        constraint = (
            BrokerConstraint.objects
            .filter(broker=broker_account.broker, symbol=symbol)
            .first()
        )

        if constraint:
            return constraint

        try:
            constraint = BrokerConstraintSyncService.sync_symbol_constraint(
                broker_account=broker_account,
                symbol=symbol,
            )
        except Exception as exc:
            logger.warning(
                "Impossible de synchroniser les contraintes broker pour recommendation broker=%s symbol=%s: %s",
                broker_account.broker,
                symbol,
                exc,
            )
            constraint = None

        return constraint

    @classmethod
    def compute_final_recommendation(
        cls,
        *,
        user,
        portfolio,
        broker_account,
        opportunity: MarketOpportunity,
    ) -> AIRecommendationResult:
        risk_profile = RiskGuardService.get_default_profile(portfolio)
        input_payload = cls.build_input_payload(
            user=user,
            portfolio=portfolio,
            opportunity=opportunity,
            risk_profile=risk_profile,
        )

        output_payload, inference_log = AIInferenceService.infer(
            user=user,
            portfolio=portfolio,
            input_payload=input_payload,
        )

        recommendation_type = output_payload["recommendation_type"]
        ai_summary = output_payload["ai_summary"]
        ai_confidence = _d(output_payload["ai_confidence"])
        stake_amount = _d(output_payload["stake_amount"])

        entry_price = _d(opportunity.entry_price)
        stop_loss = _d(opportunity.stop_loss) if opportunity.stop_loss else entry_price
        take_profit = _d(opportunity.take_profit) if opportunity.take_profit else None

        constraint = cls._resolve_constraint(
            broker_account=broker_account,
            symbol=opportunity.symbol,
        )

        min_qty = getattr(constraint, "min_qty", None) or cls.DEFAULT_MIN_QTY
        qty_step = getattr(constraint, "qty_step", None) or cls.DEFAULT_QTY_STEP
        min_notional = getattr(constraint, "min_notional", None) or cls.DEFAULT_MIN_NOTIONAL

        # Capital Preservation First : le plafond dur de risque de la classe
        # d'instrument s'applique au sizing (ne peut que réduire).
        from risk.instruments import classify as _classify_instrument

        try:
            sizing = PositionSizingService.compute(
                portfolio=portfolio,
                risk_profile=risk_profile,
                entry_price=entry_price,
                stop_loss=stop_loss,
                requested_stake=stake_amount,
                min_qty=min_qty,
                qty_step=qty_step,
                min_notional=min_notional,
                leverage=cls.DEFAULT_LEVERAGE,
                instrument_tier=_classify_instrument(
                    getattr(opportunity, "asset", None), symbol=opportunity.symbol,
                ),
            )
        except ValueError as exc:
            message = str(exc)

            logger.info(
                "Recommendation sizing blocked symbol=%s broker=%s stake=%s reason=%s",
                opportunity.symbol,
                broker_account.broker,
                stake_amount,
                message,
            )

            return AIRecommendationResult(
                recommendation_type="WATCH",
                ai_summary=(
                    f"{ai_summary} Recommandation abaissée à WATCH : "
                    f"non exécutable avec les contraintes broker actuelles ({message})."
                ),
                ai_confidence=ai_confidence,
                stake_amount=Decimal("0"),
                recommended_quantity=Decimal("0"),
                recommended_notional=Decimal("0"),
                expected_risk_amount=Decimal("0"),
                expected_reward_amount=Decimal("0"),
                risk_reward_ratio=Decimal("0"),
                decision_payload={
                    "inference_log_id": inference_log.id,
                    "raw_ai_output": output_payload,
                    "risk_preview": {},
                    "risk_decision_preview": "WATCH",
                    "risk_blocking_reason": message,
                    "broker_constraint_id": getattr(constraint, "id", None),
                    "min_qty": str(min_qty),
                    "qty_step": str(qty_step),
                    "min_notional": str(min_notional),
                    "recommendation_degraded": True,
                    "degraded_reason": "broker_constraint_not_met",
                },
            )

        approval = RiskGuardService.validate_trade(
            portfolio=portfolio,
            symbol=opportunity.symbol,
            asset=opportunity.asset,
            side="BUY" if opportunity.direction in ["BUY", "CALL"] else "SELL",
            requested_stake=sizing.requested_stake,
            approved_quantity=sizing.quantity,
            approved_notional=sizing.notional,
            entry_price=entry_price,
            stop_loss=_d(opportunity.stop_loss) if opportunity.stop_loss else None,
            take_profit=take_profit,
            confidence=ai_confidence,
            signal=None,
            trade_idea=None,
        )

        final_type = recommendation_type
        if approval.decision in {"BLOCK", "REJECT"}:
            final_type = "WATCH"

        final_stake = approval.approved_stake if approval.decision == "REDUCE" else sizing.requested_stake
        final_quantity = approval.approved_quantity if approval.decision == "REDUCE" else sizing.quantity
        final_notional = approval.approved_notional if approval.decision == "REDUCE" else sizing.notional

        return AIRecommendationResult(
            recommendation_type=final_type,
            ai_summary=ai_summary,
            ai_confidence=ai_confidence,
            stake_amount=final_stake,
            recommended_quantity=final_quantity,
            recommended_notional=final_notional,
            expected_risk_amount=approval.expected_loss,
            expected_reward_amount=approval.expected_gain,
            risk_reward_ratio=approval.risk_reward_ratio,
            decision_payload={
                "inference_log_id": inference_log.id,
                "raw_ai_output": output_payload,
                "risk_preview": approval.payload,
                "risk_decision_preview": approval.decision,
                "risk_blocking_reason": approval.blocking_reason,
                "broker_constraint_id": getattr(constraint, "id", None),
                "min_qty": str(min_qty),
                "qty_step": str(qty_step),
                "min_notional": str(min_notional),
            },
        )

    @classmethod
    @transaction.atomic
    def create_recommendation(
        cls,
        *,
        user,
        portfolio,
        broker_account,
        opportunity: MarketOpportunity,
    ) -> TradeRecommendation:
        result = cls.compute_final_recommendation(
            user=user,
            portfolio=portfolio,
            broker_account=broker_account,
            opportunity=opportunity,
        )

        status_map = {
            "WATCH": "PENDING",
            "PLAN": "APPROVED_BY_AI",
            "EXECUTE": "APPROVED_BY_AI",
        }

        recommendation = TradeRecommendation.objects.create(
            user=user,
            portfolio=portfolio,
            broker_account=broker_account,
            opportunity=opportunity,
            recommendation_type=result.recommendation_type,
            status=status_map.get(result.recommendation_type, "PENDING"),
            stake_amount=result.stake_amount,
            recommended_quantity=result.recommended_quantity,
            recommended_notional=result.recommended_notional,
            expected_risk_amount=result.expected_risk_amount,
            expected_reward_amount=result.expected_reward_amount,
            risk_reward_ratio=result.risk_reward_ratio,
            ai_confidence=result.ai_confidence,
            ai_summary=result.ai_summary,
            decision_payload=result.decision_payload,
            expires_at=opportunity.expires_at,
        )

        DecisionAudit.objects.create(
            user=user,
            portfolio=portfolio,
            opportunity=opportunity,
            recommendation=recommendation,
            ai_output=result.decision_payload.get("raw_ai_output", {}),
            sizing_output={
                "stake_amount": str(result.stake_amount),
                "recommended_quantity": str(result.recommended_quantity),
                "recommended_notional": str(result.recommended_notional),
            },
            risk_output={
                "expected_risk_amount": str(result.expected_risk_amount),
                "expected_reward_amount": str(result.expected_reward_amount),
                "risk_reward_ratio": str(result.risk_reward_ratio),
                "preview": result.decision_payload.get("risk_preview", {}),
                "preview_decision": result.decision_payload.get("risk_decision_preview"),
                "blocking_reason": result.decision_payload.get("risk_blocking_reason"),
            },
            execution_output={},
            final_decision=recommendation.status,
            notes=result.ai_summary,
        )

        RealtimeBroadcastService.broadcast_ai_update(
            user_id=user.id,
            payload={
                "kind": "recommendation_created",
                "recommendation_id": recommendation.id,
                "symbol": opportunity.symbol,
                "direction": opportunity.direction,
                "recommendation_type": recommendation.recommendation_type,
                "status": recommendation.status,
                "stake_amount": str(recommendation.stake_amount),
                "recommended_notional": str(recommendation.recommended_notional),
                "ai_confidence": str(recommendation.ai_confidence),
            },
        )

        TradingNotificationService.notify_success(
            user_id=user.id,
            message=f"Nouvelle recommandation IA détectée sur {opportunity.symbol}",
            payload={
                "recommendation_id": recommendation.id,
                "symbol": opportunity.symbol,
            },
        )

        return recommendation