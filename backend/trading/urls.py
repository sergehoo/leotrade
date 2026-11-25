from django.urls import path

from trading.views import SignalListView, ExecuteSignalView, OrderListView, market_data_api, OrderDetailView, \
    TradingIntentListView, TradingIntentCreateView, TradingIntentDetailView, TradingIntentAnalyzeView, \
    TradingIntentLaunchView, signal_list_api
from trading.views_deriv import DerivContractListView, DerivContractDetailView
from trading.views_hedge_fund import HedgeFundDashboardView, RiskMonitorView, LearningMonitorView, risk_monitor_api, learning_monitor_api
from trading.views_trade_ideas import TradeIdeaListView, TradeIdeaDetailView, TradeIdeaApproveView, TradeIdeaRejectView, \
    TradeIdeaAutoTradeView, TradeIdeaLiveFeedView

app_name = "trading"

urlpatterns = [
    path("api/market-data/", market_data_api, name="market-data"),
    path("signals/", SignalListView.as_view(), name="signal-list"),
    path("signals/api/", signal_list_api, name="signal-list-api"),
    path("orders/", OrderListView.as_view(), name="order-list"),
    path("signals/<int:pk>/execute/", ExecuteSignalView.as_view(), name="execute-signal"),

    path("orders/<int:pk>/", OrderDetailView.as_view(), name="order-detail"),

    path("intents/", TradingIntentListView.as_view(), name="intent-list"),
    path("intents/create/", TradingIntentCreateView.as_view(), name="intent-create"),
    path("intents/<int:pk>/", TradingIntentDetailView.as_view(), name="intent-detail"),
    path("intents/<int:pk>/analyze/", TradingIntentAnalyzeView.as_view(), name="intent-analyze"),
    path("intents/<int:pk>/launch/", TradingIntentLaunchView.as_view(), name="intent-launch"),

    path("deriv/contracts/", DerivContractListView.as_view(), name="deriv-contract-list"),
    path("deriv/contracts/<int:pk>/", DerivContractDetailView.as_view(), name="deriv-contract-detail"),

    path("ideas/", TradeIdeaListView.as_view(), name="trade-idea-list"),
    path("ideas/live-feed/", TradeIdeaLiveFeedView.as_view(), name="trade-idea-live-feed"),
    path("ideas/<int:pk>/", TradeIdeaDetailView.as_view(), name="trade-idea-detail"),
    path("ideas/<int:pk>/approve/", TradeIdeaApproveView.as_view(), name="trade-idea-approve"),
    path("ideas/<int:pk>/reject/", TradeIdeaRejectView.as_view(), name="trade-idea-reject"),
    path("ideas/<int:pk>/auto-trade/", TradeIdeaAutoTradeView.as_view(), name="trade-idea-auto-trade"),

    path("hedge-fund/", HedgeFundDashboardView.as_view(), name="hedge-fund-dashboard"),
    path("hedge-fund/risk/", RiskMonitorView.as_view(), name="risk-monitor"),
    path("hedge-fund/risk/api/", risk_monitor_api, name="risk-monitor-api"),
    path("hedge-fund/learning/", LearningMonitorView.as_view(), name="learning-monitor"),
    path("hedge-fund/learning/api/", learning_monitor_api, name="learning-monitor-api"),
]
