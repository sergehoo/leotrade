from django.urls import path
from .views import AssistantSessionView, ActionConfirmView, ActionRejectView, PendingActionsView

app_name = "ai_assistant"

urlpatterns = [
    path("session/", AssistantSessionView.as_view(), name="session"),
    path("action/<int:pk>/confirm/", ActionConfirmView.as_view(), name="action_confirm"),
    path("action/<int:pk>/reject/", ActionRejectView.as_view(), name="action_reject"),
    path("actions/pending/", PendingActionsView.as_view(), name="pending_actions"),
]
