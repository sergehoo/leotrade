"""
api/views/wallet.py
===================

Portefeuille électronique en REST v1.

Aucune route de ce module ne déclenche de flux financier :

  - les dépôts ne sont pas initiables ici. Un dépôt passe par un
    fournisseur de paiement et crée un débit réel sur l'instrument de
    paiement de l'utilisateur ; l'ouvrir depuis une API cliente sans
    intégration validée reviendrait à activer un flux d'argent réel ;
  - une demande de retrait est créée à l'état PENDING et attend une
    revue humaine. Elle verrouille des fonds, elle n'en déplace aucun.

Le reste est en lecture.
"""

from __future__ import annotations

import logging

from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.serializers.wallet import (
    WalletLedgerEntrySerializer,
    WalletSummarySerializer,
    WalletTransactionSerializer,
    WithdrawalCreateSerializer,
    WithdrawalRequestSerializer,
)
from wallet.models import Wallet, WalletLedgerEntry, WalletTransaction, WithdrawalRequest
from wallet.services_summary import WalletSummaryService

log = logging.getLogger("leotrade.api.wallet")


class WalletSummaryView(APIView):
    """GET /api/v1/wallet/summary/"""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: WalletSummarySerializer},
        summary="Soldes, capital de trading et état du rapprochement",
        description=(
            "Sépare l'argent réel du portefeuille électronique et le capital "
            "des portefeuilles de trading, celui-ci distingué selon qu'il "
            "engage ou non de l'argent réel. Porte aussi l'état du "
            "rapprochement : un solde que le grand livre n'explique pas est "
            "une information qui appartient à son propriétaire."
        ),
    )
    def get(self, request):
        return Response(
            WalletSummarySerializer(WalletSummaryService.build(request.user)).data
        )


class WalletLedgerViewSet(viewsets.ReadOnlyModelViewSet):
    """Grand livre — l'historique qui doit expliquer le solde."""

    serializer_class = WalletLedgerEntrySerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["entry_type", "currency"]
    ordering_fields = ["created_at", "amount"]
    ordering = ["-created_at"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return WalletLedgerEntry.objects.none()
        return WalletLedgerEntry.objects.filter(
            wallet__user=self.request.user,
        ).order_by("-created_at")


class WalletTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = WalletTransactionSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["tx_type", "status", "provider"]
    ordering_fields = ["created_at", "amount"]
    ordering = ["-created_at"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return WalletTransaction.objects.none()
        return WalletTransaction.objects.filter(
            wallet__user=self.request.user,
        ).order_by("-created_at")


class WithdrawalRequestViewSet(viewsets.ModelViewSet):
    """Demandes de retrait.

    Création et annulation seulement : approuver ou payer relève d'une
    revue humaine, hors de portée du titulaire du compte.
    """

    serializer_class = WithdrawalRequestSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ["status"]
    ordering = ["-created_at"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return WithdrawalRequest.objects.none()
        return WithdrawalRequest.objects.filter(
            wallet__user=self.request.user,
        ).order_by("-created_at")

    def get_throttles(self):
        if self.action in {"create", "cancel"}:
            self.throttle_scope = "sensitive"
        return super().get_throttles()

    @extend_schema(
        request=WithdrawalCreateSerializer,
        responses={201: WithdrawalRequestSerializer},
        summary="Demander un retrait (aucun fonds n'est déplacé)",
    )
    def create(self, request, *args, **kwargs):
        payload = WithdrawalCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data

        wallet = Wallet.objects.filter(user=request.user).first()
        if wallet is None:
            return Response(
                {"code": "NO_WALLET", "detail": "Aucun portefeuille électronique."},
                status=status.HTTP_409_CONFLICT,
            )

        # Garde KYC : même règle que `wallet/views.py`. Un retrait sort de
        # l'argent du système ; l'exposer sans la garde ferait de l'API le
        # chemin de contournement.
        profile = getattr(request.user, "kyc_profile", None)
        if getattr(profile, "status", None) != "APPROVED":
            return Response(
                {
                    "code": "KYC_REQUIRED",
                    "detail": "Ton dossier KYC doit être approuvé avant tout retrait.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if not wallet.is_active:
            return Response(
                {"code": "WALLET_INACTIVE", "detail": "Portefeuille désactivé."},
                status=status.HTTP_409_CONFLICT,
            )

        amount = data["amount"]
        if not wallet.has_sufficient_balance(amount):
            return Response(
                {
                    "code": "INSUFFICIENT_FUNDS",
                    "detail": "Solde disponible insuffisant pour ce retrait.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        from wallet.services import WalletService

        try:
            # Le service verrouille les fonds ET écrit au grand livre.
            # Passer par lui plutôt que de créer l'objet directement est
            # ce qui garantit que le solde reste expliqué par l'historique.
            withdrawal, _transaction = WalletService.lock_funds_for_withdrawal(
                wallet,
                amount,
                destination_type=data.get("destination_type") or "BANK",
                destination_masked=data.get("destination_masked") or "",
            )
        except Exception as exc:
            log.warning(
                "wallet.withdrawal_request_failed user_id=%s error=%s",
                request.user.pk, exc,
            )
            return Response(
                {"code": "WITHDRAWAL_FAILED", "detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            WithdrawalRequestSerializer(withdrawal).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        request=None,
        responses={200: WithdrawalRequestSerializer},
        summary="Annuler une demande encore en attente",
    )
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        withdrawal = self.get_object()
        if withdrawal.status not in {"PENDING", "UNDER_REVIEW"}:
            return Response(
                {
                    "code": "NOT_CANCELLABLE",
                    "detail": (
                        "Cette demande n'est plus annulable : elle a déjà été "
                        "traitée."
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )

        from wallet.services import WalletService

        try:
            WalletService.cancel_withdrawal(withdrawal)
        except AttributeError:
            # Le service legacy n'expose pas d'annulation. On refuse
            # explicitement plutôt que de changer le statut sans libérer
            # les fonds verrouillés — ce qui laisserait de l'argent bloqué.
            return Response(
                {
                    "code": "CANCEL_UNAVAILABLE",
                    "detail": (
                        "L'annulation en libre-service n'est pas disponible. "
                        "Contacte le support pour libérer les fonds."
                    ),
                },
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )
        except Exception as exc:
            return Response(
                {"code": "CANCEL_FAILED", "detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        withdrawal.refresh_from_db()
        return Response(WithdrawalRequestSerializer(withdrawal).data)
