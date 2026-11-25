from django.urls import path
from .views import StrategyListView, StrategyDetailView,StrategyToggleActiveView,StrategyToggleAutonomousView,StrategySwitchStatusView,StrategyDeploymentActivateView,StrategyDeploymentPauseView,SignalListView,SignalDetailView,SignalApproveView,SignalRejectView,StrategyRunListView,StrategyRunDetailView, strategy_list_api
urlpatterns = [
    path("", StrategyListView.as_view(), name="strategy-list"),
    path("api/", strategy_list_api, name="strategy-list-api"),
    path("<int:pk>/", StrategyDetailView.as_view(), name="strategy-detail"),

    path("<int:pk>/toggle-active/", StrategyToggleActiveView.as_view(), name="strategy-toggle-active"),
    path("<int:pk>/toggle-autonomous/", StrategyToggleAutonomousView.as_view(), name="strategy-toggle-autonomous"),
    path("<int:pk>/switch-status/", StrategySwitchStatusView.as_view(), name="strategy-switch-status"),
    path("<int:pk>/deployments/activate/", StrategyDeploymentActivateView.as_view(), name="strategy-deployment-activate"),
    path("<int:pk>/deployments/<int:deployment_id>/pause/", StrategyDeploymentPauseView.as_view(), name="strategy-deployment-pause"),

    path("signals/", SignalListView.as_view(), name="signal-list"),
    path("signals/<int:pk>/", SignalDetailView.as_view(), name="signal-detail"),
    path("signals/<int:pk>/approve/", SignalApproveView.as_view(), name="signal-approve"),
    path("signals/<int:pk>/reject/", SignalRejectView.as_view(), name="signal-reject"),

    path("runs/", StrategyRunListView.as_view(), name="strategy-run-list"),
    path("runs/<int:pk>/", StrategyRunDetailView.as_view(), name="strategy-run-detail"),
]
