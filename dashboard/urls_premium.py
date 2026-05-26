from django.urls import path
from dashboard.views_premium import (
    PremiumCockpitView,
    CockpitDataView,
    RecommendationApproveView,
    RecommendationRejectView,
    RecommendationExecuteView,
    ResolveKillSwitchView,
)

app_name = "dashboard"

urlpatterns = [
    path("premium/", PremiumCockpitView.as_view(), name="premium_cockpit"),
    path("premium/data/", CockpitDataView.as_view(), name="premium_cockpit_data"),

    path("premium/recommendations/<int:pk>/approve/", RecommendationApproveView.as_view(), name="recommendation_approve"),
    path("premium/recommendations/<int:pk>/reject/", RecommendationRejectView.as_view(), name="recommendation_reject"),
    path("premium/recommendations/<int:pk>/execute/", RecommendationExecuteView.as_view(), name="recommendation_execute"),

    path("premium/portfolio/<int:portfolio_id>/resolve-kill-switch/", ResolveKillSwitchView.as_view(), name="resolve_kill_switch"),
]