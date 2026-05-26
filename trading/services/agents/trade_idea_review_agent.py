from __future__ import annotations

from trading.models import TradeIdeaReview
from trading.services.agents.base import BaseAgentService


class TradeIdeaReviewAgent(BaseAgentService):
    agent_type = "TRADE_IDEA_REVIEW"

    @classmethod
    def review(cls, ideas, regime_snapshot=None):
        run = cls.start_run(
            input_payload={
                "idea_ids": [idea.id for idea in ideas],
                "regime": regime_snapshot.regime if regime_snapshot else None,
            }
        )

        created_reviews = []

        try:
            regime = regime_snapshot.regime if regime_snapshot else "MIXED"
            posture = regime_snapshot.risk_posture if regime_snapshot else "NEUTRAL"

            ranked = []
            for idea in ideas:
                adjustment = 0.0
                market_alignment_score = 0.5
                portfolio_fit_score = 0.7
                decision = "REVIEW"
                reasoning = []

                if regime == "TREND_BULLISH":
                    if idea.direction in ["BUY", "CALL"]:
                        adjustment += 0.08
                        market_alignment_score = 0.90
                        reasoning.append("Alignée avec un régime haussier global.")
                    else:
                        adjustment -= 0.10
                        market_alignment_score = 0.30
                        reasoning.append("Contre le régime haussier dominant.")
                elif regime == "TREND_BEARISH":
                    if idea.direction in ["SELL", "PUT"]:
                        adjustment += 0.08
                        market_alignment_score = 0.90
                        reasoning.append("Alignée avec un régime baissier global.")
                    else:
                        adjustment -= 0.10
                        market_alignment_score = 0.30
                        reasoning.append("Contre le régime baissier dominant.")
                elif regime == "VOLATILE":
                    adjustment -= 0.07
                    market_alignment_score = 0.40
                    portfolio_fit_score = 0.50
                    reasoning.append("Volatilité élevée, prudence renforcée.")
                elif regime == "RANGE":
                    adjustment -= 0.02
                    reasoning.append("Marché en range, confirmation requise.")

                if idea.risk_score > 0.75:
                    adjustment -= 0.08
                    reasoning.append("Niveau de risque jugé élevé.")
                if idea.expected_rr >= 2.0:
                    adjustment += 0.05
                    reasoning.append("Ratio rendement/risque attractif.")
                if idea.confidence_score >= 0.80:
                    adjustment += 0.05
                    reasoning.append("Confiance technique élevée.")

                adjusted_score = max(0.0, min(1.0, idea.overall_score + adjustment))

                if adjusted_score >= 0.78:
                    decision = "APPROVE"
                elif adjusted_score <= 0.52:
                    decision = "REJECT"

                ranked.append({
                    "idea": idea,
                    "adjustment": adjustment,
                    "adjusted_score": adjusted_score,
                    "decision": decision,
                    "reasoning": " ".join(reasoning) if reasoning else "Configuration correcte mais nécessite supervision.",
                    "market_alignment_score": market_alignment_score,
                    "portfolio_fit_score": portfolio_fit_score,
                })

            ranked.sort(key=lambda x: x["adjusted_score"], reverse=True)

            for idx, item in enumerate(ranked, start=1):
                review = TradeIdeaReview.objects.update_or_create(
                    idea=item["idea"],
                    defaults={
                        "agent_run": run,
                        "decision": item["decision"],
                        "priority": idx,
                        "confidence_adjustment": item["adjustment"],
                        "adjusted_score": item["adjusted_score"],
                        "reasoning": item["reasoning"],
                        "portfolio_fit_score": item["portfolio_fit_score"],
                        "market_alignment_score": item["market_alignment_score"],
                        "payload": {
                            "regime": regime,
                            "posture": posture,
                        },
                    }
                )[0]
                created_reviews.append(review)

            cls.finish_run(
                run,
                output_payload={"reviewed_count": len(created_reviews)},
                notes=f"Reviewed {len(created_reviews)} ideas under regime {regime}",
            )
            return created_reviews

        except Exception as exc:
            cls.finish_run(run, success=False, error_message=str(exc))
            raise