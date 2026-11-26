from django.urls import path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from api.views.auth import LoginMFAView, LoginView, LogoutView, MeView
from api.views.context import AppContextView

# Leo — l'assistant est déjà écrit et déjà protégé par `IsAuthenticated`,
# donc déjà compatible JWT. Il n'était simplement pas monté sous /api/v1/ :
# les clients React et Flutter devaient viser /assistant/api/..., une URL
# héritée du panneau Django. On l'expose ici sans le déplacer, pour que le
# panneau historique continue de fonctionner.
from ai_assistant.api import (
    AssistantConversationViewSet,
    action_request_cancel,
    action_request_confirm,
    action_requests,
    assistant_analytics,
    assistant_command,
    assistant_history,
    assistant_tools,
)

from api.views.brokers import BrokerAccountViewSet, BrokerConstraintViewSet
from api.views.portfolio import PortfolioViewSet, PositionViewSet, PortfolioSnapshotViewSet, CashLedgerEntryViewSet, \
    PortfolioAllocationViewSet, PositionCorrelationViewSet

from api.views.execution import OrderViewSet, ExecutionEventViewSet, ExecutionFillViewSet, BrokerSyncLogViewSet

from api.views.risk import (
    RiskProfileViewSet,
    DailyRiskStateViewSet,
    WeeklyRiskStateViewSet,
    RiskDecisionViewSet,
    KillSwitchEventViewSet,
    RiskUtilityViewSet,
)
from api.views.ai import (
    MarketScanRunViewSet,
    MarketOpportunityViewSet,
    TradeRecommendationViewSet,
    AIModelRegistryViewSet,
    AIInferenceLogViewSet,
    DecisionAuditViewSet,
)
router = DefaultRouter()
router.register(r"portfolios", PortfolioViewSet, basename="api-portfolios")
router.register(r"positions", PositionViewSet, basename="api-positions")
router.register(r"snapshots", PortfolioSnapshotViewSet, basename="api-snapshots")
router.register(r"ledger", CashLedgerEntryViewSet, basename="api-ledger")
router.register(r"allocations", PortfolioAllocationViewSet, basename="api-allocations")
router.register(r"correlations", PositionCorrelationViewSet, basename="api-correlations")

router.register(r"orders", OrderViewSet, basename="api-orders")
router.register(r"fills", ExecutionFillViewSet, basename="api-fills")
router.register(r"events", ExecutionEventViewSet, basename="api-events")
router.register(r"sync-logs", BrokerSyncLogViewSet, basename="api-sync-logs")

router.register(r"risk-profiles", RiskProfileViewSet, basename="api-risk-profiles")
router.register(r"daily-risk-states", DailyRiskStateViewSet, basename="api-daily-risk-states")
router.register(r"weekly-risk-states", WeeklyRiskStateViewSet, basename="api-weekly-risk-states")
router.register(r"risk-decisions", RiskDecisionViewSet, basename="api-risk-decisions")
router.register(r"kill-switch-events", KillSwitchEventViewSet, basename="api-kill-switch-events")
router.register(r"risk-utils", RiskUtilityViewSet, basename="api-risk-utils")

router.register(r"scan-runs", MarketScanRunViewSet, basename="api-scan-runs")
router.register(r"opportunities", MarketOpportunityViewSet, basename="api-opportunities")
router.register(r"recommendations", TradeRecommendationViewSet, basename="api-recommendations")
router.register(r"ai-models", AIModelRegistryViewSet, basename="api-ai-models")
router.register(r"ai-inference-logs", AIInferenceLogViewSet, basename="api-ai-inference-logs")
router.register(r"decision-audits", DecisionAuditViewSet, basename="api-decision-audits")
router.register(
    r"assistant/conversations",
    AssistantConversationViewSet,
    basename="api-assistant-conversations",
)

router.register(r"brokers", BrokerAccountViewSet, basename="api-brokers")
router.register(r"broker-constraints", BrokerConstraintViewSet, basename="api-broker-constraints")


# Le refresh est throttlé au même titre que la connexion : c'est une surface
# d'attaque équivalente (un refresh token volé y est rejoué).
class ThrottledTokenRefreshView(TokenRefreshView):
    throttle_scope = "auth"


urlpatterns = [
    # ── Authentification ───────────────────────────────────────────────
    path("auth/login/", LoginView.as_view(), name="api-auth-login"),
    path("auth/login/mfa/", LoginMFAView.as_view(), name="api-auth-login-mfa"),
    path("auth/refresh/", ThrottledTokenRefreshView.as_view(), name="api-auth-refresh"),
    path("auth/verify/", TokenVerifyView.as_view(), name="api-auth-verify"),
    path("auth/logout/", LogoutView.as_view(), name="api-auth-logout"),
    path("auth/me/", MeView.as_view(), name="api-auth-me"),
    # ── Contexte applicatif ────────────────────────────────────────────
    path("context/", AppContextView.as_view(), name="api-context"),
    # ── Leo ────────────────────────────────────────────────────────────
    path("assistant/history/", assistant_history, name="api-assistant-history"),
    path("assistant/analytics/", assistant_analytics, name="api-assistant-analytics"),
    path("assistant/tools/", assistant_tools, name="api-assistant-tools"),
    path("assistant/command/", assistant_command, name="api-assistant-command"),
    path(
        "assistant/action-requests/",
        action_requests,
        name="api-assistant-action-requests",
    ),
    path(
        "assistant/action-requests/<int:pk>/confirm/",
        action_request_confirm,
        name="api-assistant-action-confirm",
    ),
    path(
        "assistant/action-requests/<int:pk>/cancel/",
        action_request_cancel,
        name="api-assistant-action-cancel",
    ),
    # ── Contrat d'API ──────────────────────────────────────────────────
    path("schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
    path("redoc/", SpectacularRedocView.as_view(url_name="api-schema"), name="api-redoc"),
] + router.urls
