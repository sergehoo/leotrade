from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.utils import timezone

from portfolio.models import Portfolio
from execution.models import Order
from risk.models import RiskDecision, KillSwitchEvent
from trading.models_ai import TradeRecommendation, MarketOpportunity, DecisionAudit


def _sd(value, default=Decimal("0")) -> Decimal:
    """Conversion Decimal robuste, renvoie *default* si la valeur est invalide."""
    try:
        if value is None or value == "":
            return default
        d = Decimal(str(value))
        return d
    except (InvalidOperation, TypeError, ValueError):
        return default


def _sf(value, default=0.0) -> float:
    """Conversion float robuste."""
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError, InvalidOperation):
        return float(default)


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

        # Positions chargées en premier pour alimenter le filtre d'opportunités
        positions = list(
            portfolio.positions
            .filter(status__in=["OPEN", "PARTIALLY_CLOSED"])
            .select_related("asset")
            .order_by("-opened_at")[:15]
        )

        orders = list(
            Order.objects
            .filter(user=user, portfolio=portfolio)
            .select_related("asset", "broker_account", "trade_idea")
            .prefetch_related("fills")
            .order_by("-created_at")[:15]
        )

        # Les opportunités de marché sont globales (pas d'owner) ; on
        # priorise néanmoins celles dont l'asset correspond aux positions ouvertes.
        portfolio_asset_ids: list[int] = [
            p.asset_id for p in positions if getattr(p, "asset_id", None)
        ]
        opp_qs = (
            MarketOpportunity.objects
            .filter(status="ACTIVE")
            .select_related("asset")
            .order_by("-overall_score", "-created_at")
        )
        if portfolio_asset_ids:
            from django.db.models import Case, When, IntegerField
            opp_qs = opp_qs.annotate(
                priority=Case(
                    When(asset_id__in=portfolio_asset_ids, then=0),
                    default=1,
                    output_field=IntegerField(),
                )
            ).order_by("priority", "-overall_score", "-created_at")

        opportunities = list(opp_qs[:12])

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

        balance = _sd(getattr(portfolio, "current_balance", None))
        equity = _sd(getattr(portfolio, "equity", None)) or balance
        available_cash = _sd(getattr(portfolio, "available_cash", None))
        locked_cash = _sd(getattr(portfolio, "locked_cash", None))
        unrealized_pnl = _sd(getattr(portfolio, "unrealized_pnl", None))
        realized_pnl = _sd(getattr(portfolio, "realized_pnl", None))
        margin_used = _sd(getattr(portfolio, "margin_used", None))
        drawdown = _sf(getattr(portfolio, "current_drawdown_percent", None))
        max_drawdown = _sf(getattr(portfolio, "max_drawdown_percent", None))

        hero_stats = {
            "balance": balance,
            "equity": equity,
            "available_cash": available_cash,
            "locked_cash": locked_cash,
            "unrealized_pnl": unrealized_pnl,
            "realized_pnl": realized_pnl,
            "total_pnl": realized_pnl + unrealized_pnl,
            "margin_used": margin_used,
            "drawdown": drawdown,
            "max_drawdown": max_drawdown,
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