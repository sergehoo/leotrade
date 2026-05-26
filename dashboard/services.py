from __future__ import annotations

from django.utils import timezone

from portfolio.models import Portfolio
from execution.models import Order
from risk.models import RiskDecision, KillSwitchEvent
from trading.models_ai import TradeRecommendation, MarketOpportunity, DecisionAudit


class DashboardPremiumService:
    @staticmethod
    def get_user_default_portfolio(user):
        return (
            Portfolio.objects
            .filter(user=user, is_active=True)
            .select_related("broker_account")
            .order_by("-is_default", "name")
            .first()
        )

    @staticmethod
    def build_cockpit_context(user, portfolio=None):
        portfolio = portfolio or DashboardPremiumService.get_user_default_portfolio(user)

        if not portfolio:
            return {
                "portfolio": None,
                "hero_stats": {},
                "recommendations": [],
                "opportunities": [],
                "orders": [],
                "positions": [],
                "risk_decisions": [],
                "kill_switch": None,
                "activity_feed": [],
            }

        recommendations = list(
            TradeRecommendation.objects
            .filter(user=user, portfolio=portfolio)
            .select_related("opportunity", "broker_account")
            .order_by("-created_at")[:12]
        )

        opportunities = list(
            MarketOpportunity.objects
            .filter(status="ACTIVE")
            .select_related("asset")
            .order_by("-overall_score", "-created_at")[:12]
        )

        orders = list(
            Order.objects
            .filter(user=user, portfolio=portfolio)
            .select_related("asset", "broker_account", "trade_idea")
            .prefetch_related("fills")
            .order_by("-created_at")[:15]
        )

        positions = list(
            portfolio.positions
            .filter(status__in=["OPEN", "PARTIALLY_CLOSED"])
            .select_related("asset")
            .order_by("-opened_at")[:15]
        )

        risk_decisions = list(
            RiskDecision.objects
            .filter(portfolio=portfolio)
            .select_related("risk_profile", "order", "trade_idea")
            .order_by("-created_at")[:10]
        )

        kill_switch = (
            KillSwitchEvent.objects
            .filter(portfolio=portfolio, is_active=True)
            .select_related("risk_profile")
            .order_by("-triggered_at")
            .first()
        )

        recent_audits = list(
            DecisionAudit.objects
            .filter(user=user, portfolio=portfolio)
            .select_related("opportunity", "recommendation", "order")
            .order_by("-created_at")[:10]
        )

        activity_feed = []
        for order in orders[:5]:
            activity_feed.append({
                "type": "order",
                "title": f"Ordre {order.symbol} {order.side}",
                "subtitle": f"Statut: {order.status}",
                "time": order.created_at,
            })

        for rec in recommendations[:5]:
            activity_feed.append({
                "type": "recommendation",
                "title": f"Reco IA {rec.opportunity.symbol}",
                "subtitle": f"{rec.recommendation_type} · {rec.status}",
                "time": rec.created_at,
            })

        for audit in recent_audits[:5]:
            activity_feed.append({
                "type": "audit",
                "title": f"Audit décisionnel {audit.final_decision}",
                "subtitle": audit.notes or "Décision journalisée",
                "time": audit.created_at,
            })

        activity_feed = sorted(activity_feed, key=lambda x: x["time"], reverse=True)[:12]

        hero_stats = {
            "balance": portfolio.current_balance,
            "equity": portfolio.equity,
            "available_cash": portfolio.available_cash,
            "locked_cash": portfolio.locked_cash,
            "unrealized_pnl": portfolio.unrealized_pnl,
            "realized_pnl": portfolio.realized_pnl,
            "margin_used": portfolio.margin_used,
            "drawdown": portfolio.current_drawdown_percent,
            "max_drawdown": portfolio.max_drawdown_percent,
            "open_positions_count": len(positions),
            "orders_count": len(orders),
            "recommendations_count": len(recommendations),
            "active_opportunities_count": len(opportunities),
            "server_time": timezone.now(),
        }

        return {
            "portfolio": portfolio,
            "hero_stats": hero_stats,
            "recommendations": recommendations,
            "opportunities": opportunities,
            "orders": orders,
            "positions": positions,
            "risk_decisions": risk_decisions,
            "kill_switch": kill_switch,
            "activity_feed": activity_feed,
        }