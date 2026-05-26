from __future__ import annotations

from trading.services.agents.market_regime_agent import MarketRegimeAgent
from trading.services.agents.trade_idea_review_agent import TradeIdeaReviewAgent
from trading.services.trade_idea_generation import TradeIdeaGenerationService


class TradingIntelligenceOrchestrator:
    @classmethod
    def run_market_cycle(cls, timeframe_code: str | None = None, user=None):
        ideas = TradeIdeaGenerationService.generate(timeframe_code=timeframe_code, user=user)

        if not ideas:
            return {
                "ideas": [],
                "regime_snapshot": None,
                "reviews": [],
            }

        scan_run = ideas[0].scan_run
        rows = []
        for idea in ideas:
            rows.append({
                "features": idea.features_snapshot,
                "asset": idea.asset,
                "timeframe": idea.timeframe,
            })

        regime_snapshot = MarketRegimeAgent.analyze(market_scan_run=scan_run, rows=rows)
        reviews = TradeIdeaReviewAgent.review(ideas=ideas, regime_snapshot=regime_snapshot)

        for review in reviews:
            if review.decision == "APPROVE":
                review.idea.status = "APPROVED"
            elif review.decision == "REJECT":
                review.idea.status = "REJECTED"
            else:
                review.idea.status = "REVIEW"
            review.idea.save(update_fields=["status", "updated_at"])

        return {
            "ideas": ideas,
            "regime_snapshot": regime_snapshot,
            "reviews": reviews,
        }