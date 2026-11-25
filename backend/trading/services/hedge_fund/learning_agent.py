from __future__ import annotations

from statistics import mean, pstdev

from portfolio.models import Position
from trading.models import TradeIdeaFeedback
from trading.models_hedge_fund import LearningSnapshot, ReinforcementEvent


class LearningAgent:
    @staticmethod
    def compute_metrics(feedbacks):
        total = len(feedbacks)
        if total == 0:
            return {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "breakevens": 0,
                "win_rate": 0.0,
                "avg_pnl": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "payoff_ratio": 0.0,
                "expectancy": 0.0,
                "sharpe_like": 0.0,
                "drawdown_penalty": 0.0,
                "confidence_multiplier": 1.0,
                "risk_multiplier": 1.0,
                "size_multiplier": 1.0,
            }

        pnls = [float(f.pnl_amount or 0) for f in feedbacks]
        wins_list = [p for p in pnls if p > 0]
        losses_list = [p for p in pnls if p < 0]
        breakevens = len([p for p in pnls if p == 0])

        wins = len(wins_list)
        losses = len(losses_list)
        avg_pnl = mean(pnls) if pnls else 0.0
        avg_win = mean(wins_list) if wins_list else 0.0
        avg_loss = abs(mean(losses_list)) if losses_list else 0.0
        win_rate = wins / total if total else 0.0
        payoff_ratio = (avg_win / avg_loss) if avg_loss else 0.0
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

        sharpe_like = 0.0
        if len(pnls) > 1 and pstdev(pnls) > 0:
            sharpe_like = avg_pnl / pstdev(pnls)

        drawdown_penalty = 0.0
        if losses >= wins and total >= 5:
            drawdown_penalty = min(0.5, losses / total)

        confidence_multiplier = 1.0
        risk_multiplier = 1.0
        size_multiplier = 1.0

        if total >= 10:
            if win_rate >= 0.60 and expectancy > 0:
                confidence_multiplier = 1.10
                risk_multiplier = 1.10
                size_multiplier = 1.08
            elif win_rate < 0.45 or expectancy < 0:
                confidence_multiplier = 0.90
                risk_multiplier = 0.80
                size_multiplier = 0.85

        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "breakevens": breakevens,
            "win_rate": round(win_rate, 4),
            "avg_pnl": round(avg_pnl, 4),
            "avg_win": round(avg_win, 4),
            "avg_loss": round(avg_loss, 4),
            "payoff_ratio": round(payoff_ratio, 4),
            "expectancy": round(expectancy, 4),
            "sharpe_like": round(sharpe_like, 4),
            "drawdown_penalty": round(drawdown_penalty, 4),
            "confidence_multiplier": round(confidence_multiplier, 4),
            "risk_multiplier": round(risk_multiplier, 4),
            "size_multiplier": round(size_multiplier, 4),
        }

    @classmethod
    def refresh_for_strategy(cls, strategy):
        feedbacks = list(
            TradeIdeaFeedback.objects.filter(
                idea__strategy=strategy,
                outcome__in=["WIN", "LOSS", "BREAKEVEN"],
            ).order_by("-created_at")[:200]
        )

        metrics = cls.compute_metrics(feedbacks)

        asset = getattr(strategy, "asset", None)
        timeframe = getattr(strategy, "timeframe", None)

        snapshot = LearningSnapshot.objects.create(
            strategy=strategy,
            asset=asset,
            timeframe=timeframe,
            **metrics,
            payload={"source": "LearningAgent.refresh_for_strategy"},
        )
        return snapshot

    @classmethod
    def reinforcement_from_feedback(cls, feedback):
        pnl = float(feedback.pnl_amount or 0)
        reward = max(0.0, pnl)
        penalty = abs(min(0.0, pnl))
        net = reward - penalty

        ReinforcementEvent.objects.create(
            idea=feedback.idea,
            signal=feedback.signal,
            strategy=getattr(feedback.idea, "strategy", None),
            event_type="TRADE_CLOSED",
            reward_value=reward,
            penalty_value=penalty,
            net_value=net,
            context_payload={
                "idea_score": feedback.idea.overall_score if feedback.idea else None,
                "confidence": feedback.idea.confidence_score if feedback.idea else None,
            },
            result_payload={
                "outcome": feedback.outcome,
                "pnl_amount": pnl,
                "pnl_percent": feedback.pnl_percent,
            },
        )