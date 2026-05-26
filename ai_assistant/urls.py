from django.urls import path
from .views import (
    AssistantSessionView,
    ActionConfirmView,
    ActionRejectView,
    PendingActionsView,
    QuotaStatusView,
    QuotaSuccessView,
    QuotaCancelView,
    stripe_webhook,
)

app_name = "ai_assistant"

urlpatterns = [
    # Session & actions
    path("session/", AssistantSessionView.as_view(), name="session"),
    path("action/<int:pk>/confirm/", ActionConfirmView.as_view(), name="action_confirm"),
    path("action/<int:pk>/reject/", ActionRejectView.as_view(), name="action_reject"),
    path("actions/pending/", PendingActionsView.as_view(), name="pending_actions"),
    # Quota & billing
    path("quota/", QuotaStatusView.as_view(), name="quota_status"),
    path("quota/success/", QuotaSuccessView.as_view(), name="quota_success"),
    path("quota/cancel/", QuotaCancelView.as_view(), name="quota_cancel"),
    path("quota/stripe/webhook/", stripe_webhook, name="stripe_webhook"),
]
