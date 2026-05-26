from django.urls import path
from .views import StrategyListView, StrategyDetailView,StrategyToggleActiveView,StrategyToggleAutonomousView,StrategySwitchStatusView,SignalListView,SignalDetailView,SignalApproveView,SignalRejectView,StrategyRunListView,StrategyRunDetailView
urlpatterns = [
    path("", StrategyListView.as_view(), name="strategy-list"),
    path("<int:pk>/", StrategyDetailView.as_view(), name="strategy-detail"),

    path("<int:pk>/toggle-active/", StrategyToggleActiveView.as_view(), name="strategy-toggle-active"),
    path("<int:pk>/toggle-autonomous/", StrategyToggleAutonomousView.as_view(), name="strategy-toggle-autonomous"),
    path("<int:pk>/switch-status/", StrategySwitchStatusView.as_view(), name="strategy-switch-status"),

    path("signals/", SignalListView.as_view(), name="signal-list"),
    path("signals/<int:pk>/", SignalDetailView.as_view(), name="signal-detail"),
    path("signals/<int:pk>/approve/", SignalApproveView.as_view(), name="signal-approve"),
    path("signals/<int:pk>/reject/", SignalRejectView.as_view(), name="signal-reject"),

    path("runs/", StrategyRunListView.as_view(), name="strategy-run-list"),
    path("runs/<int:pk>/", StrategyRunDetailView.as_view(), name="strategy-run-detail"),
]