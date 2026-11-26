from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from api.permissions import IsOwner
from api.serializers.ai import (
    MarketScanRunSerializer,
    MarketOpportunitySerializer,
    TradeRecommendationSerializer,
    AIModelRegistrySerializer,
    AIInferenceLogSerializer,
    DecisionAuditSerializer,
)
from trading.models_ai import (
    MarketScanRun,
    MarketOpportunity,
    TradeRecommendation,
    AIModelRegistry,
    AIInferenceLog,
    DecisionAudit,
)
from trading.services.recommendation_actions import RecommendationActionService
from trading.tasks_ai import generate_ai_recommendations_for_portfolio_task
from portfolio.models import Portfolio


class MarketScanRunViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Liste les runs de scan marché. Filtré par utilisateur (via portfolio si dispo).
    Avant : retournait .all() → fuite inter-utilisateurs des stratégies de scan.
    """
    serializer_class = MarketScanRunSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        user = self.request.user
        qs = MarketScanRun.objects.all()
        # MarketScanRun n'a pas forcément un FK direct user. On filtre via les
        # FK courants : user, portfolio, broker_account.
        # On essaie chacun, le premier qui matche le schéma s'applique.
        for filter_kwargs in (
            {"user": user},
            {"portfolio__user": user},
            {"broker_account__user": user},
        ):
            try:
                return qs.filter(**filter_kwargs).order_by("-started_at")
            except Exception:
                continue
        # Filtre de dernier recours : aucun ; sinon on renvoie vide pour ne pas leaker
        return qs.none()


class MarketOpportunityViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Opportunities scannées. Filtre par utilisateur via portfolio.
    Avant : .all() → fuite des opportunités d'autres users.
    """
    serializer_class = MarketOpportunitySerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        user = self.request.user
        qs = MarketOpportunity.objects.all()
        for filter_kwargs in (
            {"user": user},
            {"portfolio__user": user},
            {"scan_run__user": user},
            {"scan_run__portfolio__user": user},
        ):
            try:
                return qs.filter(**filter_kwargs).order_by("-overall_score", "-created_at")
            except Exception:
                continue
        return qs.none()


class TradeRecommendationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TradeRecommendationSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        return (
            TradeRecommendation.objects
            .filter(user=self.request.user)
            .select_related("portfolio", "broker_account", "opportunity")
            .order_by("-created_at")
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        recommendation = self.get_object()
        recommendation = RecommendationActionService.approve_by_user(recommendation)
        return Response(TradeRecommendationSerializer(recommendation, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        recommendation = self.get_object()
        recommendation = RecommendationActionService.reject_by_user(recommendation)
        return Response(TradeRecommendationSerializer(recommendation, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def execute(self, request, pk=None):
        recommendation = self.get_object()
        result = RecommendationActionService.execute_recommendation(recommendation)
        return Response({
            "status": "ok",
            "order_id": result["order"].id,
            "order_status": result["order"].status,
        })

    @action(detail=False, methods=["post"], url_path="generate-for-portfolio")
    def generate_for_portfolio(self, request):
        portfolio_id = request.data.get("portfolio_id")
        if not portfolio_id:
            return Response({"detail": "portfolio_id requis."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            portfolio_id = int(portfolio_id)
        except (TypeError, ValueError):
            return Response(
                {"detail": "portfolio_id invalide."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        portfolio = get_object_or_404(
            Portfolio.objects.filter(user=request.user, is_active=True),
            pk=portfolio_id,
        )
        result = generate_ai_recommendations_for_portfolio_task.delay(portfolio.pk)
        return Response({"status": "queued", "task_id": str(result.id)})


class AIModelRegistryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AIModelRegistrySerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        return AIModelRegistry.objects.filter(is_active=True).order_by("name")


class AIInferenceLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AIInferenceLogSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        return (
            AIInferenceLog.objects
            .filter(user=self.request.user)
            .select_related("portfolio", "model")
            .order_by("-created_at")
        )


class DecisionAuditViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DecisionAuditSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        return (
            DecisionAudit.objects
            .filter(user=self.request.user)
            .select_related("portfolio", "opportunity", "recommendation", "risk_decision", "order")
            .order_by("-created_at")
        )
