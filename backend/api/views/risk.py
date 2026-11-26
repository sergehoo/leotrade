from drf_spectacular.utils import extend_schema
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
from risk.services_summary import RiskSummaryService


class RiskProfileViewSet(viewsets.ModelViewSet):
    serializer_class = RiskProfileSerializer
    permission_classes = [IsOwner]
    filterset_fields = ["portfolio", "is_active", "is_default", "preservation_mode"]
    search_fields = ["name"]
    ordering = ["portfolio_id", "-is_default", "name"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return RiskProfile.objects.none()
        return RiskProfile.objects.filter(user=self.request.user).select_related("portfolio")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["post"], url_path="set-default")
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
        if getattr(self, "swagger_fake_view", False):
            return DailyRiskState.objects.none()
        return DailyRiskState.objects.filter(portfolio__user=self.request.user).select_related("portfolio")


class WeeklyRiskStateViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = WeeklyRiskStateSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return WeeklyRiskState.objects.none()
        return WeeklyRiskState.objects.filter(portfolio__user=self.request.user).select_related("portfolio")


class RiskDecisionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RiskDecisionSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return RiskDecision.objects.none()
        return RiskDecision.objects.filter(portfolio__user=self.request.user).select_related("portfolio", "risk_profile")


class KillSwitchEventViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = KillSwitchEventSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return KillSwitchEvent.objects.none()
        return KillSwitchEvent.objects.filter(portfolio__user=self.request.user).select_related("portfolio", "risk_profile")

    @action(detail=False, methods=["post"], url_path="resolve-for-portfolio")
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

    def _owned_portfolio(self, request, portfolio_id):
        """Un portefeuille d'autrui doit être indiscernable d'un inexistant."""
        from portfolio.models import Portfolio

        return Portfolio.objects.filter(id=portfolio_id, user=request.user).first()

    @extend_schema(
        summary="État consolidé du Risk Control pour un portefeuille",
        description=(
            "Limites, consommation, drawdown, kill switch et politique de "
            "préservation. Le taux d'utilisation est le chiffre décisif : "
            "connaître la limite n'apprend rien, savoir qu'on en a consommé "
            "80 % change la décision."
        ),
    )
    @action(detail=False, methods=["get"], url_path=r"summary/(?P<portfolio_id>\d+)")
    def summary(self, request, portfolio_id=None):
        portfolio = self._owned_portfolio(request, portfolio_id)
        if not portfolio:
            return Response(
                {"detail": "Portfolio introuvable."}, status=status.HTTP_404_NOT_FOUND,
            )
        return Response(RiskSummaryService.build(portfolio))

    @action(detail=False, methods=["post"], url_path="refresh-states")
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