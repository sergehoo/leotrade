from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views.generic import TemplateView, View

from portfolio.models import Portfolio
from dashboard.services import DashboardPremiumService
from trading.models_ai import TradeRecommendation
from trading.services.recommendation_actions import RecommendationActionService
from risk.services import RiskGuardService


class PremiumCockpitView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/premium/cockpit.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        portfolio_id = self.request.GET.get("portfolio")
        portfolio = None
        if portfolio_id:
            portfolio = Portfolio.objects.filter(
                id=portfolio_id,
                user=self.request.user,
                is_active=True,
            ).select_related("broker_account").first()

        cockpit = DashboardPremiumService.build_cockpit_context(
            user=self.request.user,
            portfolio=portfolio,
        )

        context.update(cockpit)
        context["all_portfolios"] = (
            Portfolio.objects
            .filter(user=self.request.user, is_active=True)
            .select_related("broker_account")
            .order_by("-is_default", "name")
        )
        return context


class CockpitDataView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        portfolio_id = request.GET.get("portfolio")
        portfolio = None
        if portfolio_id:
            portfolio = Portfolio.objects.filter(
                id=portfolio_id,
                user=request.user,
                is_active=True,
            ).first()

        data = DashboardPremiumService.build_cockpit_context(
            user=request.user,
            portfolio=portfolio,
        )
        portfolio_obj = data["portfolio"]

        return JsonResponse({
            "portfolio": {
                "id": portfolio_obj.id if portfolio_obj else None,
                "name": portfolio_obj.name if portfolio_obj else None,
                "broker": portfolio_obj.broker_account.name if portfolio_obj else None,
            } if portfolio_obj else None,
            "hero_stats": {
                key: str(value) for key, value in data["hero_stats"].items()
            },
            "recommendations": [
                {
                    "id": r.id,
                    "symbol": r.opportunity.symbol,
                    "direction": r.opportunity.direction,
                    "recommendation_type": r.recommendation_type,
                    "status": r.status,
                    "stake_amount": str(r.stake_amount),
                    "recommended_notional": str(r.recommended_notional),
                    "ai_confidence": str(r.ai_confidence),
                    "summary": r.ai_summary or "",
                }
                for r in data["recommendations"]
            ],
            "orders": [
                {
                    "id": o.id,
                    "symbol": o.symbol,
                    "side": o.side,
                    "status": o.status,
                    "mode": o.mode,
                    "approved_quantity": str(o.approved_quantity),
                    "filled_quantity": str(o.filled_quantity),
                    "approved_notional": str(o.approved_notional),
                }
                for o in data["orders"]
            ],
            "positions": [
                {
                    "id": p.id,
                    "symbol": p.symbol,
                    "side": p.side,
                    "quantity": str(p.quantity),
                    "entry_price": str(p.entry_price),
                    "current_price": str(p.current_price),
                    "pnl": str(p.pnl),
                    "pnl_percent": p.pnl_percent,
                    "status": p.status,
                }
                for p in data["positions"]
            ],
            "kill_switch": {
                "id": data["kill_switch"].id,
                "reason_code": data["kill_switch"].reason_code,
                "reason": data["kill_switch"].reason,
            } if data["kill_switch"] else None,
        })


class RecommendationApproveView(LoginRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        recommendation = TradeRecommendation.objects.filter(
            id=pk,
            user=request.user,
        ).select_related("opportunity", "portfolio", "broker_account").first()

        if not recommendation:
            messages.error(request, "Recommandation introuvable.")
            return redirect("dashboard:premium_cockpit")

        RecommendationActionService.approve_by_user(recommendation)
        messages.success(request, "Recommandation approuvée.")
        return redirect("dashboard:premium_cockpit")


class RecommendationRejectView(LoginRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        recommendation = TradeRecommendation.objects.filter(
            id=pk,
            user=request.user,
        ).select_related("opportunity").first()

        if not recommendation:
            messages.error(request, "Recommandation introuvable.")
            return redirect("dashboard:premium_cockpit")

        RecommendationActionService.reject_by_user(recommendation)
        messages.success(request, "Recommandation rejetée.")
        return redirect("dashboard:premium_cockpit")


class RecommendationExecuteView(LoginRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        recommendation = TradeRecommendation.objects.filter(
            id=pk,
            user=request.user,
        ).select_related("opportunity", "portfolio", "broker_account").first()

        if not recommendation:
            messages.error(request, "Recommandation introuvable.")
            return redirect("dashboard:premium_cockpit")

        try:
            RecommendationActionService.execute_recommendation(recommendation)
            messages.success(request, "Recommandation exécutée avec succès.")
        except Exception as exc:
            messages.error(request, f"Échec exécution : {exc}")

        return redirect("dashboard:premium_cockpit")


class ResolveKillSwitchView(LoginRequiredMixin, View):
    def post(self, request, portfolio_id, *args, **kwargs):
        portfolio = Portfolio.objects.filter(
            id=portfolio_id,
            user=request.user,
            is_active=True,
        ).first()

        # Redirige vers la page d'origine si fournie (pour rester dans le
        # contexte de la trade idea / du formulaire d'exécution), sinon
        # fallback sur le cockpit premium.
        next_url = (
            request.POST.get("next")
            or request.META.get("HTTP_REFERER")
            or "dashboard:premium_cockpit"
        )

        if not portfolio:
            messages.error(request, "Portefeuille introuvable.")
            return redirect(next_url)

        count = RiskGuardService.resolve_kill_switch(portfolio)
        if count:
            messages.success(
                request,
                f"{count} kill switch(s) résolu(s) sur {portfolio.name}. "
                f"Tu peux relancer l'exécution."
            )
        else:
            messages.info(
                request,
                f"Aucun kill switch actif sur {portfolio.name}."
            )
        return redirect(next_url)