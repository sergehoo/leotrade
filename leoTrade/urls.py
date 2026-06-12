"""
URL configuration for leoTrade project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include

from core.health import health_live, health_ready
from leo_backtesting.views import BacktestListView, LaunchBacktestView, BacktestDetailView
from dashboard.views import HedgeFundDashboardView, LandingPageView
from strategies.views import StrategyListView, StrategyDetailView
from trading.views import SignalListView, ExecuteSignalView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("accounts/", include("allauth_2fa.urls")),
    path("dashboard/", include("dashboard.urls")),
path("api/v1/", include("api.urls")),
    # Strategies
    path("strategies/", include("strategies.urls")),
    path("wallet/", include("wallet.urls")),
    path("trading/", include("trading.urls",namespace="trading")),
    path("backtests/", include("leo_backtesting.urls")),
    path("risk/", include("risk.urls")),
    path("portfolio/", include("portfolio.urls")),
    # Alias rétrocompatibilité : ancienne URL avec typo. À supprimer après migration des liens.
    path("portofolio/", include("portfolio.urls")),
    path("market/", include("market.urls")),
    path("brokers/", include("brokers.urls")),
    path("notifications/", include("notifications.urls", namespace="notifications")),
    path("api/notifications/", include("notifications.urls_api")),
    path("ai/", include("ai_engine.urls")),
    path("assistant/", include("ai_assistant.urls", namespace="ai_assistant")),
    path("", LandingPageView.as_view(), name="landing_page"),
path("health/live/", health_live, name="health_live"),
path("health/ready/", health_ready, name="health_ready"),
path("", include("django_prometheus.urls")),

]
