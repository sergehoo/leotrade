"""
api/views/market.py
===================

Marchés : instruments, cotations, historiques et liste de suivi.

Toute cotation sort datée et qualifiée. Voir
`market/services_quotes.py` pour le raisonnement : sur la base de
développement, les 46 instruments se déclarent « OPEN » alors que leur
dernière bougie a cinq mois. Un prix sans date est un prix qu'on croit
courant.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from api.permissions import IsOwner
from api.serializers.market import (
    AssetSerializer,
    CandleHistorySerializer,
    QuoteSerializer,
    WatchlistItemSerializer,
)
from market.models import Asset
from market.models_watchlist import WatchlistItem
from market.services_quotes import MarketQuoteService


class AssetViewSet(viewsets.ReadOnlyModelViewSet):
    """Catalogue d'instruments. Lecture seule : le catalogue est alimenté
    par les connecteurs de données, pas par les clients."""

    serializer_class = AssetSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["asset_class", "exchange", "is_active"]
    search_fields = ["symbol", "name", "base_asset", "quote_asset"]
    ordering_fields = ["symbol", "asset_class", "exchange"]
    ordering = ["symbol"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Asset.objects.none()
        queryset = Asset.objects.all()
        # Les instruments retirés restent accessibles en détail — une
        # position ouverte peut encore les référencer — mais sortent de
        # la liste par défaut.
        if self.action == "list" and self.request.query_params.get("is_active") is None:
            queryset = queryset.filter(is_active=True)
        return queryset.order_by("symbol")

    @extend_schema(
        parameters=[
            OpenApiParameter("timeframe", str, description="Unité de temps (1h, 1d…)."),
        ],
        responses={200: QuoteSerializer(many=True)},
        summary="Cotations des instruments listés, chacune datée",
    )
    @action(detail=False, methods=["get"])
    def quotes(self, request):
        timeframe = request.query_params.get("timeframe")
        # Pagination appliquée AVANT le calcul : chaque cotation coûte
        # deux requêtes de bougies, en coter 300 d'un coup rendrait
        # l'endpoint inutilisable.
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        assets = page if page is not None else list(self.get_queryset()[:50])

        rows = MarketQuoteService.quotes_for(assets, timeframe)
        data = QuoteSerializer(rows, many=True).data
        if page is not None:
            return self.get_paginated_response(data)
        return Response(data)

    @extend_schema(
        parameters=[OpenApiParameter("timeframe", str)],
        responses={200: QuoteSerializer},
        summary="Dernier cours connu d'un instrument",
    )
    @action(detail=True, methods=["get"])
    def quote(self, request, pk=None):
        asset = self.get_object()
        row = MarketQuoteService.quote(asset, request.query_params.get("timeframe"))
        return Response(QuoteSerializer(row).data)

    @extend_schema(
        parameters=[
            OpenApiParameter("timeframe", str),
            OpenApiParameter("limit", int, description="1 à 1000, 200 par défaut."),
        ],
        responses={200: CandleHistorySerializer},
        summary="Historique de bougies pour les graphiques",
    )
    @action(detail=True, methods=["get"])
    def candles(self, request, pk=None):
        asset = self.get_object()
        history = MarketQuoteService.history(
            asset,
            timeframe_code=request.query_params.get("timeframe"),
            limit=request.query_params.get("limit") or 200,
        )
        return Response(CandleHistorySerializer(history).data)


class WatchlistViewSet(viewsets.ModelViewSet):
    """Liste de suivi — une préférence d'affichage, propre à l'utilisateur."""

    serializer_class = WatchlistItemSerializer
    permission_classes = [IsOwner]
    ordering = ["position", "created_at"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return WatchlistItem.objects.none()
        return (
            WatchlistItem.objects
            .filter(user=self.request.user)
            .select_related("asset")
            .order_by("position", "created_at")
        )

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Suivre deux fois le même instrument n'a pas de sens : on rend
        # l'entrée existante plutôt qu'une erreur de contrainte, pour que
        # le bouton « suivre » reste idempotent.
        existing = WatchlistItem.objects.filter(
            user=request.user, asset=serializer.validated_data["asset"],
        ).first()
        if existing is not None:
            return Response(self.get_serializer(existing).data, status=status.HTTP_200_OK)

        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        parameters=[OpenApiParameter("timeframe", str)],
        responses={200: QuoteSerializer(many=True)},
        summary="Cotations des instruments suivis",
    )
    @action(detail=False, methods=["get"])
    def quotes(self, request):
        assets = [item.asset for item in self.get_queryset()]
        rows = MarketQuoteService.quotes_for(
            assets, request.query_params.get("timeframe"),
        )
        return Response(QuoteSerializer(rows, many=True).data)
