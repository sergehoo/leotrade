from django.urls import path

from .views import advise_trade_idea_view, list_decisions_view

app_name = "ai_engine"

urlpatterns = [
    path("advise/trade-idea/<int:idea_id>/", advise_trade_idea_view, name="advise_trade_idea"),
    path("decisions/", list_decisions_view, name="list_decisions"),
]
