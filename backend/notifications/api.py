"""
API REST du module notifications (DRF).

  GET   /api/notifications/                 — liste paginée, filtres
  GET   /api/notifications/unread-count/    — badge non-lu
  POST  /api/notifications/{id}/mark-read/  — marquer lue
  POST  /api/notifications/mark-all-read/   — tout marquer lu
  GET   /api/notifications/preferences/     — préférences
  PATCH /api/notifications/preferences/     — mise à jour préférences

Filtres de liste : ?event_type= &severity= &priority= &status=
                   &unread=true &since=ISO8601 &until=ISO8601
"""

from __future__ import annotations

from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from .models import Notification
from .serializers import NotificationPreferenceSerializer, NotificationSerializer
from .services import NotificationPreferenceService, NotificationService


class NotificationPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


class NotificationViewSet(ReadOnlyModelViewSet):
    """Notifications de l'utilisateur courant uniquement."""

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = NotificationPagination

    def get_queryset(self):
        qs = Notification.objects.filter(user=self.request.user)

        params = self.request.query_params
        event_type = params.get("event_type")
        severity = params.get("severity")
        priority = params.get("priority")
        notif_status = params.get("status")
        unread = params.get("unread")
        since = params.get("since")
        until = params.get("until")

        if event_type:
            qs = qs.filter(event_type=event_type)
        if severity:
            qs = qs.filter(severity=severity.upper())
        if priority:
            qs = qs.filter(priority=priority.upper())
        if notif_status:
            qs = qs.filter(status=notif_status.upper())
        if unread in ("true", "1"):
            qs = qs.filter(read_at__isnull=True)
        if since and (dt := parse_datetime(since)):
            qs = qs.filter(created_at__gte=dt)
        if until and (dt := parse_datetime(until)):
            qs = qs.filter(created_at__lte=dt)

        return qs.order_by("-created_at")

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        return Response({"unread": NotificationService.unread_count(request.user)})

    @action(detail=True, methods=["post"], url_path="mark-read")
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        notification.mark_read()
        return Response({
            "id": notification.id,
            "read_at": notification.read_at,
            "unread": NotificationService.unread_count(request.user),
        })

    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request):
        updated = NotificationService.mark_all_read(request.user)
        return Response({"marked": updated, "unread": 0})

    @action(detail=False, methods=["get", "patch"], url_path="preferences")
    def preferences(self, request):
        pref = NotificationPreferenceService.get_or_create(request.user)
        if request.method == "PATCH":
            serializer = NotificationPreferenceSerializer(
                pref, data=request.data, partial=True,
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(NotificationPreferenceSerializer(pref).data)
