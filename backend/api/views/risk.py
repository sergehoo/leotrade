from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from api.permissions import IsOwner
from api.serializers.risk import (
    RiskProfileSerializer,
    DailyRiskStateSerializer,
    WeeklyRiskStateSerializer,
    RiskDecisionSerializer,
    KillSwitchEventSerializer,
)
from risk.models import RiskProfile, DailyRiskState, WeeklyRiskState, RiskDecision, KillSwitchEvent
from risk.services import RiskStateService, RiskGuardService


class RiskProfileViewSet(viewsets.ModelViewSet):
    serializer_class = RiskProfileSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        return RiskProfile.objects.filter(user=self.request.user).select_related("portfolio")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["post"])
    def set_default(self, request, pk=None):
        profile = self.get_object()
        RiskProfile.objects.filter(
            portfolio=profile.portfolio,
            is_default=True,
        ).exclude(pk=profile.pk).update(is_default=False)

        profile.is_default = True
        profile.save(update_fields=["is_default", "updated_at"])
        return Response({"status": "ok"})


class DailyRiskStateViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DailyRiskStateSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        return DailyRiskState.objects.filter(portfolio__user=self.request.user).select_related("portfolio")


class WeeklyRiskStateViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = WeeklyRiskStateSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        return WeeklyRiskState.objects.filter(portfolio__user=self.request.user).select_related("portfolio")


class RiskDecisionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RiskDecisionSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        return RiskDecision.objects.filter(portfolio__user=self.request.user).select_related("portfolio", "risk_profile")


class KillSwitchEventViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = KillSwitchEventSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        return KillSwitchEvent.objects.filter(portfolio__user=self.request.user).select_related("portfolio", "risk_profile")

    @action(detail=False, methods=["post"])
    def resolve_for_portfolio(self, request):
        portfolio_id = request.data.get("portfolio_id")
        from portfolio.models import Portfolio

        portfolio = Portfolio.objects.filter(id=portfolio_id, user=request.user).first()
        if not portfolio:
            return Response({"detail": "Portfolio introuvable."}, status=status.HTTP_404_NOT_FOUND)

        count = RiskGuardService.resolve_kill_switch(portfolio)
        return Response({"status": "ok", "resolved_count": count})


class RiskUtilityViewSet(viewsets.ViewSet):
    permission_classes = [IsOwner]

    @action(detail=False, methods=["post"])
    def refresh_states(self, request):
        from portfolio.models import Portfolio

        portfolio_id = request.data.get("portfolio_id")
        portfolio = Portfolio.objects.filter(id=portfolio_id, user=request.user).first()
        if not portfolio:
            return Response({"detail": "Portfolio introuvable."}, status=status.HTTP_404_NOT_FOUND)

        daily = RiskStateService.refresh_daily_state(portfolio)
        weekly = RiskStateService.refresh_weekly_state(portfolio)

        return Response({
            "daily_state_id": daily.id,
            "weekly_state_id": weekly.id,
            "daily_loss_percent": str(daily.total_loss_percent),
            "weekly_loss_percent": str(weekly.total_loss_percent),
        })