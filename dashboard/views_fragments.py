from django.contrib.auth.mixins import LoginRequiredMixin
from django.template.response import TemplateResponse
from django.views import View

from portfolio.models import Portfolio
from dashboard.services import DashboardPremiumService


class AIPartialView(LoginRequiredMixin, View):
    template_name = "dashboard/premium/partials/_ai_radar.html"

    def get(self, request, *args, **kwargs):
        portfolio_id = request.GET.get("portfolio")
        portfolio = Portfolio.objects.filter(id=portfolio_id, user=request.user).first() if portfolio_id else None
        context = DashboardPremiumService.build_cockpit_context(request.user, portfolio)
        return TemplateResponse(request, self.template_name, context)