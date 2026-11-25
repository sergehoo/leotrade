from django.http import Http404
from trading.models import TradeIdea


class UserScopedTradeIdeaMixin:
    def get_tradeidea_queryset(self):
        user = self.request.user

        return (
            TradeIdea.objects
            .select_related("asset", "timeframe", "strategy", "signal", "feedback", "review")
            .filter(user=user)
            .order_by("-overall_score", "-created_at")
        )

    def get_tradeidea(self):
        obj = self.get_tradeidea_queryset().filter(pk=self.kwargs["pk"]).first()
        if not obj:
            raise Http404("TradeIdea introuvable.")
        return obj