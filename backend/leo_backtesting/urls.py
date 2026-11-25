from django.urls import path

from leo_backtesting.views import (
    BacktestListView,
    BacktestDetailView,
    LaunchBacktestView,
    BacktestStatusView,
)

urlpatterns = [
    path("", BacktestListView.as_view(), name="backtest-list"),
    path("<int:pk>/", BacktestDetailView.as_view(), name="backtest-detail"),
    path("<int:pk>/status/", BacktestStatusView.as_view(), name="backtest-status"),
    path("launch/<int:strategy_id>/", LaunchBacktestView.as_view(), name="launch-backtest"),
]