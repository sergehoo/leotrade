from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from brokers.models import BrokerAccount, BrokerConstraint
from brokers.services.base import BrokerConstraintSyncService
from brokers.services_connection import BrokerConnectionService
# from brokers.services_constraints import BrokerConstraintSyncService
from api.permissions import IsOwner
from rest_framework import serializers


class BrokerAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = BrokerAccount
        fields = [
            "id", "name", "broker", "mode", "login", "server",
            "deriv_app_id", "deriv_currency", "deriv_account_type",
            "is_active", "is_default", "status",
            "last_connection_status", "last_connection_error", "last_connected_at",
            "notes", "created_at", "updated_at",
        ]
        read_only_fields = ["status", "last_connection_status", "last_connection_error", "last_connected_at"]


class BrokerConstraintSerializer(serializers.ModelSerializer):
    class Meta:
        model = BrokerConstraint
        fields = "__all__"


class BrokerAccountViewSet(viewsets.ModelViewSet):
    serializer_class = BrokerAccountSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        return BrokerAccount.objects.filter(user=self.request.user).order_by("name")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["post"])
    def test_connection(self, request, pk=None):
        broker = self.get_object()
        result = BrokerConnectionService.test_connection(broker)

        if result["success"]:
            return Response({"status": "ok", "payload": result["payload"]})
        return Response({"status": "error", "error": result["error"]}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def sync_constraint(self, request, pk=None):
        broker = self.get_object()
        symbol = request.data.get("symbol")
        if not symbol:
            return Response({"detail": "symbol requis."}, status=status.HTTP_400_BAD_REQUEST)

        constraint = BrokerConstraintSyncService.sync_symbol_constraint(broker, symbol)
        return Response(BrokerConstraintSerializer(constraint).data)


class BrokerConstraintViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = BrokerConstraintSerializer
    permission_classes = [IsOwner]

    def get_queryset(self):
        user_brokers = BrokerAccount.objects.filter(user=self.request.user).values_list("broker", flat=True)
        return BrokerConstraint.objects.filter(broker__in=user_brokers).order_by("broker", "symbol")