from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Avg, Count, Sum
from django.http import JsonResponse
from django.views.generic import TemplateView

from portfolio.models import Portfolio, Position
from trading.models import TradeIdea, TradeIdeaFeedback
from trading.models_hedge_fund import (
    MarketRegimeState,
    RiskState,
    LearningSnapshot,
    ConfidenceAssessment,
    RiskPolicy,
    ReinforcementEvent,
)


class HedgeFundDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "trading/hedge_fund_dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        portfolios = Portfolio.objects.filter(user=self.request.user).select_related("broker_account")
        portfolio_ids = list(portfolios.values_list("id", flat=True))

        latest_regime = MarketRegimeState.objects.order_by("-created_at").first()
        latest_risk_states = (
            RiskState.objects.filter(portfolio_id__in=portfolio_ids)
            .select_related("portfolio")
            .order_by("portfolio_id", "-created_at")
        )

        latest_risk_by_portfolio = {}
        for rs in latest_risk_states:
            if rs.portfolio_id not in latest_risk_by_portfolio:
                latest_risk_by_portfolio[rs.portfolio_id] = rs

        ideas = (
            TradeIdea.objects.select_related("asset", "timeframe", "review", "confidence_assessment")
            .order_by("-created_at")[:20]
        )

        top_ideas = (
            TradeIdea.objects.select_related("asset", "timeframe", "review", "confidence_assessment")
            .filter(status__in=["NEW", "REVIEW", "APPROVED"])
            .order_by("-overall_score", "-created_at")[:10]
        )

        open_positions = Position.objects.filter(portfolio_id__in=portfolio_ids, status="OPEN").select_related("asset", "portfolio")
        latest_learning = LearningSnapshot.objects.order_by("-created_at")[:10]

        feedback_qs = TradeIdeaFeedback.objects.filter(
            idea__signal__strategy__isnull=False
        )

        stats = {
            "portfolio_count": portfolios.count(),
            "open_positions_count": open_positions.count(),
            "ideas_count": TradeIdea.objects.count(),
            "approved_ideas_count": TradeIdea.objects.filter(status="APPROVED").count(),
            "executed_ideas_count": TradeIdea.objects.filter(status="EXECUTED").count(),
            "win_feedback_count": feedback_qs.filter(outcome="WIN").count(),
            "loss_feedback_count": feedback_qs.filter(outcome="LOSS").count(),
            "avg_confidence": TradeIdea.objects.aggregate(v=Avg("confidence_score"))["v"] or 0,
            "avg_overall_score": TradeIdea.objects.aggregate(v=Avg("overall_score"))["v"] or 0,
            "total_open_pnl": sum([(p.pnl or 0) for p in open_positions], 0),
        }

        pnl_series = []
        for p in open_positions[:20]:
            pnl_series.append({
                "label": f"{p.asset.symbol} / {p.portfolio.name}",
                "value": float(p.pnl or 0),
            })

        idea_score_series = []
        for idea in top_ideas:
            idea_score_series.append({
                "label": f"{idea.symbol} {idea.timeframe.code}",
                "overall": float(idea.overall_score or 0),
                "confidence": float(idea.confidence_score or 0),
                "risk": float(idea.risk_score or 0),
            })

        ctx.update({
            "portfolios": portfolios,
            "latest_regime": latest_regime,
            "latest_risk_by_portfolio": latest_risk_by_portfolio,
            "ideas": ideas,
            "top_ideas": top_ideas,
            "open_positions": open_positions[:10],
            "latest_learning": latest_learning,
            "stats": stats,
            "pnl_series": pnl_series,
            "idea_score_series": idea_score_series,
        })
        return ctx


class RiskMonitorView(LoginRequiredMixin, TemplateView):
    template_name = "trading/risk_monitor.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        portfolios = Portfolio.objects.filter(user=self.request.user).select_related("broker_account")
        portfolio_ids = list(portfolios.values_list("id", flat=True))

        latest_states_qs = (
            RiskState.objects.filter(portfolio_id__in=portfolio_ids)
            .select_related("portfolio")
            .order_by("portfolio_id", "-created_at")
        )

        latest_states = []
        seen = set()
        for state in latest_states_qs:
            if state.portfolio_id not in seen:
                latest_states.append(state)
                seen.add(state.portfolio_id)

        policies = {
            p.portfolio_id: p
            for p in RiskPolicy.objects.filter(portfolio_id__in=portfolio_ids)
        }

        open_positions = (
            Position.objects.filter(portfolio_id__in=portfolio_ids, status="OPEN")
            .select_related("portfolio", "asset")
            .order_by("portfolio__name", "asset__symbol")
        )

        ctx.update({
            "latest_states": latest_states,
            "policies": policies,
            "open_positions": open_positions,
        })
        return ctx


class LearningMonitorView(LoginRequiredMixin, TemplateView):
    template_name = "trading/learning_monitor.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        snapshots = (
            LearningSnapshot.objects.select_related("strategy", "asset", "timeframe")
            .order_by("-created_at")[:50]
        )

        reinforcement_events = (
            ReinforcementEvent.objects.select_related("strategy", "idea", "signal")
            .order_by("-created_at")[:30]
        )

        top_models = snapshots[:10]

        chart_data = []
        for snap in top_models:
            label = snap.strategy.name if snap.strategy else (snap.asset.symbol if snap.asset else f"Snapshot {snap.id}")
            chart_data.append({
                "label": label[:24],
                "win_rate": float(snap.win_rate or 0),
                "expectancy": float(snap.expectancy or 0),
                "size_multiplier": float(snap.size_multiplier or 1),
            })

        ctx.update({
            "snapshots": snapshots,
            "reinforcement_events": reinforcement_events,
            "chart_data": chart_data,
        })
        return ctx


@login_required
def risk_monitor_api(request):
    """AJAX — risk states JSON."""
    portfolios = Portfolio.objects.filter(user=request.user, is_active=True)
    portfolio_ids = list(portfolios.values_list("id", flat=True))

    latest_states_qs = (
        RiskState.objects.filter(portfolio_id__in=portfolio_ids)
        .select_related("portfolio")
        .order_by("portfolio_id", "-created_at")
    )

    latest_states = {}
    for state in latest_states_qs:
        if state.portfolio_id not in latest_states:
            latest_states[state.portfolio_id] = state

    data = []
    for pid, state in latest_states.items():
        data.append({
            "portfolio_id": state.portfolio_id,
            "portfolio_name": state.portfolio.name,
            "status": state.status,
            "drawdown_pct": float(state.current_drawdown_percent or 0),
            "exposure_pct": float(state.exposure_percent or 0),
            "correlation_risk": float(state.correlation_risk_score or 0),
            "recommended_risk": float(state.recommended_risk_percent or 0),
            "allow_new_positions": state.allow_new_positions,
            "reason": state.reason or "",
        })

    return JsonResponse({"risk_states": data, "count": len(data)})


@login_required
def learning_monitor_api(request):
    """AJAX — learning snapshots + reinforcement events."""
    snapshots = LearningSnapshot.objects.select_related("strategy", "asset").order_by("-created_at")[:20]
    events = ReinforcementEvent.objects.select_related("strategy").order_by("-created_at")[:15]

    snap_data = []
    for s in snapshots:
        label = (s.strategy.name if s.strategy else (s.asset.symbol if s.asset else f"#{s.id}"))
        snap_data.append({
            "id": s.id,
            "label": label[:20],
            "win_rate": float(s.win_rate or 0),
            "expectancy": float(s.expectancy or 0),
            "size_multiplier": float(s.size_multiplier or 1),
            "created_at": s.created_at.strftime("%d/%m %H:%M") if s.created_at else "",
        })

    event_data = []
    for e in events:
        event_data.append({
            "id": e.id,
            "event_type": e.event_type,
            "strategy": e.strategy.name if e.strategy else "—",
            "net_value": float(e.net_value or 0),
            "created_at": e.created_at.strftime("%d/%m %H:%M") if e.created_at else "",
        })

    return JsonResponse({"snapshots": snap_data, "events": event_data})
