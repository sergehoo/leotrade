"""
API REST des conversations LeoAI (DRF) — montée sous /assistant/api/.

  GET    /assistant/api/conversations/            liste (pagination, ?q=, ?context_type=, ?archived=)
  POST   /assistant/api/conversations/            créer (contexte optionnel)
  GET    /assistant/api/conversations/{id}/       détail + messages
  DELETE /assistant/api/conversations/{id}/       suppression définitive
  POST   /assistant/api/conversations/{id}/archive/    archiver / désarchiver
  GET    /assistant/api/conversations/{id}/messages/   messages paginés
  GET    /assistant/api/history/                  messages récents tous contextes
  GET    /assistant/api/analytics/                stats (soi-même ; global si staff)

Sécurité : chaque queryset est filtré sur request.user — un utilisateur ne
voit jamais les conversations d'un autre. Compatible app mobile Flutter
(SessionAuth + JWT déjà configurés au niveau DRF).
"""

from __future__ import annotations

from django.db.models import Count, Q
from rest_framework import status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from .models import AssistantConversation, AssistantMessage
from .serializers_api import (
    AssistantConversationDetailSerializer,
    AssistantConversationSerializer,
    AssistantMessageSerializer,
)
from .services_conversation import ConversationService


class ConversationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class MessagePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class AssistantConversationViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
    pagination_class = ConversationPagination
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        qs = (
            AssistantConversation.objects
            .filter(user=self.request.user)
            .annotate(message_count=Count("messages"))
        )

        params = self.request.query_params
        # Le filtre archivé ne concerne que la LISTE : détail, suppression et
        # archive/désarchive doivent atteindre toutes ses conversations.
        if self.action == "list":
            archived = params.get("archived")
            if archived in ("true", "1"):
                qs = qs.filter(archived=True)
            elif archived in ("false", "0") or archived is None:
                qs = qs.filter(archived=False)
            # archived=all → pas de filtre

        context_type = params.get("context_type")
        if context_type:
            qs = qs.filter(context_type=context_type.upper())

        q = params.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(title__icontains=q) | Q(messages__content__icontains=q)
            ).distinct()

        return qs.order_by("-updated_at")

    def get_serializer_class(self):
        if self.action == "retrieve":
            return AssistantConversationDetailSerializer
        return AssistantConversationSerializer

    def perform_create(self, serializer):
        extra_ctx = {
            "page": self.request.data.get("page_context") or "dashboard",
        }
        for key in ("trade_idea_id", "position_id", "order_id", "portfolio_id",
                    "broker_account_id", "signal_id", "opportunity_id"):
            if self.request.data.get(key):
                extra_ctx[key] = self.request.data[key]
        conversation = ConversationService.get_or_create_for_context(
            self.request.user, extra_ctx,
        )
        title = (self.request.data.get("title") or "").strip()
        if title:
            conversation.title = title[:200]
            conversation.save(update_fields=["title", "updated_at"])
        serializer.instance = conversation

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        conversation = self.get_object()
        conversation.archived = not conversation.archived
        conversation.save(update_fields=["archived", "updated_at"])
        return Response({
            "id": conversation.id,
            "archived": conversation.archived,
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"])
    def messages(self, request, pk=None):
        conversation = self.get_object()
        qs = conversation.messages.prefetch_related("actions").order_by("created_at")
        paginator = MessagePagination()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(
            AssistantMessageSerializer(page, many=True).data
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def assistant_history(request):
    """Messages récents de l'utilisateur, tous contextes confondus."""
    qs = (
        AssistantMessage.objects
        .filter(conversation__user=request.user)
        .select_related("conversation")
        .prefetch_related("actions")
        .order_by("-created_at")
    )
    q = request.query_params.get("q", "").strip()
    if q:
        qs = qs.filter(content__icontains=q)

    paginator = MessagePagination()
    page = paginator.paginate_queryset(qs, request)
    data = AssistantMessageSerializer(page, many=True).data
    for entry, message in zip(data, page):
        entry["conversation_id"] = message.conversation_id
        entry["conversation_title"] = message.conversation.title
    return paginator.get_paginated_response(data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def assistant_analytics(request):
    """Statistiques d'usage : les siennes ; globales avec ?scope=global (staff)."""
    if request.query_params.get("scope") == "global" and request.user.is_staff:
        return Response(ConversationService.analytics(user=None))
    return Response(ConversationService.analytics(user=request.user))
