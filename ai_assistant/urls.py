from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .api import AssistantConversationViewSet, assistant_analytics, assistant_history
from .views import (
    AssistantConversationView,
    ConversationCenterView,
    ActionConfirmView,
    ActionRejectView,
    PendingActionsView,
    QuotaStatusView,
    QuotaSuccessView,
    QuotaCancelView,
    stripe_webhook,
)

app_name = "ai_assistant"

router = DefaultRouter()
router.register("conversations", AssistantConversationViewSet, basename="assistant-conversation")

urlpatterns = [
    # API REST conversations (web + future app Flutter)
    path("api/", include(router.urls)),
    path("api/history/", assistant_history, name="api_history"),
    path("api/analytics/", assistant_analytics, name="api_analytics"),

    # Centre des conversations (web)
    path("conversations/", ConversationCenterView.as_view(), name="conversations"),

    # Session & actions
    path("session/", AssistantConversationView.as_view(), name="session"),
    path("action/<int:pk>/confirm/", ActionConfirmView.as_view(), name="action_confirm"),
    path("action/<int:pk>/reject/", ActionRejectView.as_view(), name="action_reject"),
    path("actions/pending/", PendingActionsView.as_view(), name="pending_actions"),
    # Quota & billing
    path("quota/", QuotaStatusView.as_view(), name="quota_status"),
    path("quota/success/", QuotaSuccessView.as_view(), name="quota_success"),
    path("quota/cancel/", QuotaCancelView.as_view(), name="quota_cancel"),
    path("quota/stripe/webhook/", stripe_webhook, name="stripe_webhook"),
]
