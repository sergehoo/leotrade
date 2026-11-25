"""
URLs du module Risk Control — pages web + API REST, montées sous /risk/.

Auparavant ce fichier était vide alors que leoTrade/urls.py incluait
`/risk/` : toutes les routes /risk/* renvoyaient 404 (cause des
recommandations cassées de l'assistant). Désormais réelles et testées.
"""

from django.urls import path

from . import api
from .views import (
    EmergencyActionsView,
    KillSwitchView,
    RiskDecisionsView,
    RiskHomeView,
    RiskProfileView,
    RiskStatesView,
)

app_name = "risk"

urlpatterns = [
    # ── Pages web ────────────────────────────────────────────────────────
    path("", RiskHomeView.as_view(), name="home"),
    path("profile/", RiskProfileView.as_view(), name="profile"),
    path("kill-switch/", KillSwitchView.as_view(), name="kill-switch"),
    path("states/", RiskStatesView.as_view(), name="states"),
    path("decisions/", RiskDecisionsView.as_view(), name="decisions"),
    path("emergency-actions/", EmergencyActionsView.as_view(), name="emergency-actions"),

    # ── API REST ─────────────────────────────────────────────────────────
    path("api/profile/", api.profile, name="api-profile"),
    path("api/kill-switch/", api.kill_switch, name="api-kill-switch"),
    path("api/kill-switch/activate/", api.kill_switch_activate, name="api-kill-switch-activate"),
    path("api/kill-switch/deactivate/", api.kill_switch_deactivate, name="api-kill-switch-deactivate"),
    path("api/states/", api.states, name="api-states"),
    path("api/decisions/", api.decisions, name="api-decisions"),
    path("api/emergency/close-position/", api.emergency_close_position, name="api-emergency-close-position"),
    path("api/emergency/close-all-losing/", api.emergency_close_all_losing, name="api-emergency-close-all-losing"),
    path("api/emergency/close-all/", api.emergency_close_all, name="api-emergency-close-all"),
]
