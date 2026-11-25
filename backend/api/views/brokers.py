"""
api/views/brokers.py
====================

Cycle de vie des comptes broker exposé en REST v1.

Toute la logique métier vit dans `brokers.services_accounts` : cette couche
ne fait que traduire HTTP ↔ service. Les secrets n'apparaissent dans aucune
réponse — le sérialiseur les déclare `write_only` et la vue ne les relit
jamais.
"""

from __future__ import annotations

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from api.permissions import IsOwner
from api.serializers.brokers import (
    BrokerAccountSerializer,
    BrokerConstraintSerializer,
    BrokerHealthSerializer,
    SyncConstraintSerializer,
)
from brokers.models import BrokerAccount, BrokerConstraint
from brokers.services.base import BrokerConstraintSyncService
from brokers.services_accounts import BrokerAccountError, BrokerAccountService

log = logging.getLogger("leotrade.api.brokers")


def _business_error(exc: BrokerAccountError, http_status=status.HTTP_400_BAD_REQUEST) -> Response:
    """Erreur métier au format stable attendu par les clients web/mobile."""
    return Response({"code": exc.code, "detail": exc.message}, status=http_status)


def _model_validation_error(exc: DjangoValidationError) -> Response:
    """Traduit une ValidationError du modèle en 400 champ par champ.

    `BrokerAccount.save()` appelle `full_clean()`. Le sérialiseur rejoue ces
    règles en amont, mais une écriture concurrente peut encore les faire
    échouer au dernier moment — un 500 serait alors trompeur : la demande
    est invalide, pas le serveur.
    """
    payload = exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}
    return Response(payload, status=status.HTTP_400_BAD_REQUEST)


class BrokerAccountViewSet(viewsets.ModelViewSet):
    serializer_class = BrokerAccountSerializer
    permission_classes = [IsOwner]
    filterset_fields = ["broker", "mode", "is_active", "is_default", "status"]
    search_fields = ["name", "login", "server"]
    ordering_fields = ["name", "created_at", "last_connected_at"]
    ordering = ["-is_default", "name"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return BrokerAccount.objects.none()
        return (
            BrokerAccount.objects
            .filter(user=self.request.user)
            .prefetch_related("credentials")
            .order_by("-is_default", "name")
        )

    def get_throttles(self):
        # Les actions qui touchent réellement le broker ou ses secrets sont
        # throttlées : une boucle de tests de connexion ferait tomber le
        # circuit breaker et pourrait faire bannir nos IP côté broker.
        if self.action in {"test_connection", "sync_constraint", "create", "update", "partial_update"}:
            self.throttle_scope = "sensitive"
        return super().get_throttles()

    # ── CRUD ───────────────────────────────────────────────────────────
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data, secrets = serializer.split_secrets(dict(serializer.validated_data))

        try:
            account = BrokerAccountService.create_account(
                request.user, data=data, secrets=secrets,
            )
        except BrokerAccountError as exc:
            return _business_error(exc, status.HTTP_403_FORBIDDEN)
        except DjangoValidationError as exc:
            return _model_validation_error(exc)
        except IntegrityError:
            return Response(
                {"name": [_("Tu as déjà un compte broker portant ce nom.")]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        output = self.get_serializer(account)
        return Response(output.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        account = self.get_object()
        serializer = self.get_serializer(account, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        data, secrets = serializer.split_secrets(dict(serializer.validated_data))

        try:
            account = BrokerAccountService.update_account(
                account, data=data, secrets=secrets, actor=request.user,
            )
        except BrokerAccountError as exc:
            return _business_error(exc, status.HTTP_403_FORBIDDEN)
        except DjangoValidationError as exc:
            return _model_validation_error(exc)
        except IntegrityError:
            return Response(
                {"name": [_("Tu as déjà un compte broker portant ce nom.")]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(self.get_serializer(account).data)

    def destroy(self, request, *args, **kwargs):
        account = self.get_object()
        try:
            BrokerAccountService.assert_deletable(account)
        except BrokerAccountError as exc:
            return _business_error(exc, status.HTTP_409_CONFLICT)
        return super().destroy(request, *args, **kwargs)

    # ── Actions ────────────────────────────────────────────────────────
    @extend_schema(
        request=None,
        responses={200: BrokerAccountSerializer},
        summary="Désigner ce compte comme broker par défaut",
    )
    @action(detail=True, methods=["post"], url_path="set-default")
    def set_default(self, request, pk=None):
        account = self.get_object()
        account = BrokerAccountService.set_default(request.user, account)
        return Response(self.get_serializer(account).data)

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(description="Connexion établie."),
            400: OpenApiResponse(description="Connexion refusée par le broker."),
            409: OpenApiResponse(description="Secrets manquants — test impossible."),
        },
        summary="Tester la connexion réelle au broker",
    )
    @action(detail=True, methods=["post"], url_path="test-connection")
    def test_connection(self, request, pk=None):
        account = self.get_object()

        try:
            result = BrokerAccountService.test_connection(account)
        except BrokerAccountError as exc:
            # Secrets manquants : on refuse avant l'appel réseau plutôt que
            # de laisser le broker renvoyer une erreur d'authentification
            # opaque. 409 — l'état de la ressource empêche l'action.
            return Response(
                {
                    "code": exc.code,
                    "detail": exc.message,
                    "missing_secrets": BrokerAccountService.missing_secrets(account),
                },
                status=status.HTTP_409_CONFLICT,
            )

        payload = self.get_serializer(account).data
        if result["success"]:
            return Response({"status": "ok", "payload": result["payload"], "account": payload})

        return Response(
            {
                "code": "CONNECTION_FAILED",
                "detail": str(result.get("error") or _("Erreur inconnue")),
                "account": payload,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    @extend_schema(
        request=SyncConstraintSerializer,
        responses={200: BrokerConstraintSerializer},
        summary="Synchroniser les contraintes d'un instrument depuis le broker",
    )
    @action(detail=True, methods=["post"], url_path="sync-constraint")
    def sync_constraint(self, request, pk=None):
        account = self.get_object()
        payload = SyncConstraintSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        symbol = payload.validated_data["symbol"]

        try:
            constraint = BrokerConstraintSyncService.sync_symbol_constraint(account, symbol)
        except Exception as exc:
            log.warning(
                "broker.sync_constraint_failed account_id=%s symbol=%s error=%s",
                account.pk, symbol, exc,
            )
            return Response(
                {"code": "SYNC_FAILED", "detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(BrokerConstraintSerializer(constraint).data)

    @extend_schema(
        responses={200: BrokerHealthSerializer(many=True)},
        summary="Santé opérationnelle du parc broker",
    )
    @action(detail=False, methods=["get"])
    def health(self, request):
        rows = BrokerAccountService.health(self.get_queryset())
        return Response({
            "results": BrokerHealthSerializer(rows, many=True).data,
            "count": len(rows),
        })


class BrokerConstraintViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = BrokerConstraintSerializer
    permission_classes = [IsOwner]
    filterset_fields = ["broker", "symbol"]
    search_fields = ["symbol"]
    ordering_fields = ["broker", "symbol", "updated_at"]
    ordering = ["broker", "symbol"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return BrokerConstraint.objects.none()
        user_brokers = (
            BrokerAccount.objects
            .filter(user=self.request.user)
            .values_list("broker", flat=True)
            .distinct()
        )
        return BrokerConstraint.objects.filter(broker__in=user_brokers).order_by("broker", "symbol")
