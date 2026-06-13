"""
Vues web du module Risk Control (templates Django + Alpine, alimentés par
l'API /risk/api/). Toutes les pages exigent l'authentification.
"""

from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView


class _BaseRiskView(LoginRequiredMixin, TemplateView):
    page = ""

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["risk_page"] = self.page
        return ctx


class RiskHomeView(_BaseRiskView):
    template_name = "risk/home.html"
    page = "home"


class RiskProfileView(_BaseRiskView):
    template_name = "risk/profile.html"
    page = "profile"


class KillSwitchView(_BaseRiskView):
    template_name = "risk/kill_switch.html"
    page = "kill_switch"


class RiskStatesView(_BaseRiskView):
    template_name = "risk/states.html"
    page = "states"


class RiskDecisionsView(_BaseRiskView):
    template_name = "risk/decisions.html"
    page = "decisions"


class EmergencyActionsView(_BaseRiskView):
    template_name = "risk/emergency_actions.html"
    page = "emergency"
