from __future__ import annotations

import logging

from django.utils import timezone

from trading.models import TradeIdea
from trading.models_hedge_fund import LearningSnapshot
from trading.services.hedge_fund.market_regime_agent import MarketRegimeAgent
from trading.services.hedge_fund.risk_agent import GlobalRiskAgent
from trading.services.hedge_fund.confidence_engine import ConfidenceEngine
from trading.services.hedge_fund.position_sizer import IntelligentPositionSizer
from trading.services.trade_idea_execution import TradeIdeaExecutionService
from trading.services.trade_idea_generation import TradeIdeaGenerationService


logger = logging.getLogger(__name__)


class AIHedgeFundEngine:
    MIN_EXECUTION_CONFIDENCE = 0.65

    @classmethod
    def run_generation_cycle(cls, timeframe_code="15m", user=None):
        if user is None:
            raise ValueError("AIHedgeFundEngine.run_generation_cycle requiert un user non nul.")

        regime = MarketRegimeAgent.detect(timeframe_code=timeframe_code)
        ideas = TradeIdeaGenerationService.generate(
            timeframe_code=timeframe_code,
            user=user,
        )

        for idea in ideas:
            learning = None
            if idea.strategy:
                learning = (
                    LearningSnapshot.objects
                    .filter(strategy=idea.strategy)
                    .order_by("-created_at")
                    .first()
                )

            try:
                ConfidenceEngine.assess(
                    idea=idea,
                    regime_state=regime,
                    learning_snapshot=learning,
                    risk_state=None,
                )
            except Exception:
                logger.exception(
                    "Confidence assessment failed for idea_id=%s symbol=%s timeframe=%s",
                    idea.id,
                    idea.symbol,
                    getattr(idea.timeframe, "code", None),
                )

        return {
            "regime": regime,
            "ideas": ideas,
        }

    @classmethod
    def _reject_idea(cls, idea: TradeIdea, message: str, **extra_payload):
        idea.status = "REJECTED"
        idea.ai_payload = {
            **(idea.ai_payload or {}),
            "execution_error": message,
            "execution_rejected_at": timezone.now().isoformat(),
            **extra_payload,
        }
        idea.save(update_fields=["status", "ai_payload", "updated_at"])

        if idea.signal_id:
            base_reason = (idea.signal.reason or "").strip()
            suffix = f"Exécution rejetée: {message}"
            idea.signal.status = "REJECTED"
            idea.signal.reason = f"{base_reason}\n{suffix}".strip() if base_reason else suffix
            idea.signal.save(update_fields=["status", "reason", "updated_at"])

    @classmethod
    def execute_top_idea_for_portfolio(cls, portfolio, broker_account):
        if not portfolio:
            raise ValueError("Portfolio requis.")
        if not broker_account:
            raise ValueError("Broker account requis.")

        portfolio_user = getattr(portfolio, "user", None)
        if portfolio_user is None:
            raise ValueError("Le portefeuille n'est rattaché à aucun utilisateur.")

        risk_state = GlobalRiskAgent.evaluate(portfolio)
        if not getattr(risk_state, "allow_new_positions", False):
            logger.info(
                "Portfolio %s blocked by global risk agent: allow_new_positions=False",
                getattr(portfolio, "id", None),
            )
            return None

        if broker_account.broker == "BINANCE" and broker_account.mode == "LIVE":
            if not broker_account.last_connection_status:
                logger.warning(
                    "Broker Binance LIVE not connected for portfolio_id=%s broker_account_id=%s",
                    getattr(portfolio, "id", None),
                    getattr(broker_account, "id", None),
                )
                return None

        ideas = (
            TradeIdea.objects
            .filter(
                user=portfolio_user,
                status__in=["NEW", "APPROVED"],
            )
            .select_related(
                "confidence_assessment",
                "strategy",
                "asset",
                "timeframe",
                "signal",
            )
            .order_by(
                "confidence_assessment__execution_priority",
                "-confidence_assessment__final_confidence",
                "-overall_score",
                "-created_at",
            )
        )

        for idea in ideas:
            learning = None
            if idea.strategy:
                learning = (
                    LearningSnapshot.objects
                    .filter(strategy=idea.strategy)
                    .order_by("-created_at")
                    .first()
                )

            assessment = getattr(idea, "confidence_assessment", None)
            if not assessment:
                try:
                    regime = MarketRegimeAgent.detect(timeframe_code=idea.timeframe.code)
                    assessment = ConfidenceEngine.assess(
                        idea=idea,
                        regime_state=regime,
                        learning_snapshot=learning,
                        risk_state=risk_state,
                    )
                except Exception as exc:
                    logger.exception(
                        "Confidence assessment failed for idea_id=%s symbol=%s",
                        idea.id,
                        idea.symbol,
                    )
                    cls._reject_idea(
                        idea,
                        f"Échec de l'évaluation de confiance: {exc}",
                        rejection_stage="confidence_assessment",
                    )
                    continue

            final_confidence = float(getattr(assessment, "final_confidence", 0) or 0)
            if final_confidence < cls.MIN_EXECUTION_CONFIDENCE:
                logger.info(
                    "Idea skipped for low confidence idea_id=%s symbol=%s final_confidence=%s",
                    idea.id,
                    idea.symbol,
                    final_confidence,
                )
                continue

            if broker_account.broker == "BINANCE" and broker_account.mode == "LIVE":
                if not broker_account.last_connection_status:
                    raise ValueError("Broker Binance non validé pour exécution LIVE.")

            try:
                size = IntelligentPositionSizer.compute_size(
                    portfolio=portfolio,
                    idea=idea,
                    confidence_assessment=assessment,
                    risk_state=risk_state,
                )
            except Exception as exc:
                logger.exception(
                    "Position sizing failed for idea_id=%s symbol=%s",
                    idea.id,
                    idea.symbol,
                )
                cls._reject_idea(
                    idea,
                    f"Échec du calcul de taille: {exc}",
                    rejection_stage="intelligent_position_sizer",
                )
                continue

            if size <= 0:
                logger.warning(
                    "Idea rejected because computed size <= 0 idea_id=%s symbol=%s size=%s",
                    idea.id,
                    idea.symbol,
                    size,
                )
                cls._reject_idea(
                    idea,
                    "La taille calculée est nulle ou négative.",
                    rejection_stage="intelligent_position_sizer",
                    computed_stake_amount=str(size),
                )
                continue

            logger.info(
                "Execution candidate portfolio_id=%s idea_id=%s symbol=%s stake_amount=%s confidence=%s entry=%s stop=%s broker=%s",
                getattr(portfolio, "id", None),
                idea.id,
                idea.symbol,
                size,
                final_confidence,
                idea.entry_price,
                idea.stop_loss,
                broker_account.broker,
            )

            try:
                order = TradeIdeaExecutionService.execute(
                    idea=idea,
                    broker_account=broker_account,
                    portfolio=portfolio,
                    stake_amount=size,
                )
            except ValueError as exc:
                message = str(exc)

                logger.warning(
                    "Execution rejected portfolio_id=%s idea_id=%s symbol=%s reason=%s stake_amount=%s",
                    getattr(portfolio, "id", None),
                    idea.id,
                    idea.symbol,
                    message,
                    size,
                )

                cls._reject_idea(
                    idea,
                    message,
                    rejection_stage="trade_idea_execution",
                    sizing_source="TradeIdeaExecutionService",
                    computed_stake_amount=str(size),
                )
                continue
            except Exception as exc:
                logger.exception(
                    "Unexpected execution failure portfolio_id=%s idea_id=%s symbol=%s",
                    getattr(portfolio, "id", None),
                    idea.id,
                    idea.symbol,
                )
                cls._reject_idea(
                    idea,
                    f"Erreur inattendue d'exécution: {exc}",
                    rejection_stage="trade_idea_execution_unexpected",
                    computed_stake_amount=str(size),
                )
                continue

            if order:
                logger.info(
                    "Order executed successfully portfolio_id=%s idea_id=%s order_id=%s symbol=%s",
                    getattr(portfolio, "id", None),
                    idea.id,
                    getattr(order, "id", None),
                    idea.symbol,
                )
                return order

        return None