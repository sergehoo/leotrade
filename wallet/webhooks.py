"""
wallet/webhooks.py
==================

Webhooks de paiement Stripe + Adyen.

Garanties :
  - Signature broker validée (Stripe via SDK, Adyen via HMAC-SHA256)
  - Idempotence atomique : `select_for_update()` sur `ProviderWebhookEvent`
    pour éviter les doubles crédits sur retries simultanés
  - Crédit wallet via `WalletService.credit_wallet(external_event_id=...)`
    qui passe par `WalletLedgerService` (idempotent par event_id)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import ProviderWebhookEvent, WalletTransaction
from .services import WalletService

try:
    import stripe
    if settings.STRIPE_SECRET_KEY:
        stripe.api_key = settings.STRIPE_SECRET_KEY
except Exception:  # pragma: no cover
    stripe = None


log = logging.getLogger("leotrade.wallet.webhooks")


# =============================================================================
# Stripe
# =============================================================================

@csrf_exempt
@require_POST
@transaction.atomic
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

    if stripe is None:
        log.error("stripe.webhook.sdk_unavailable")
        return HttpResponse(status=503)

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=settings.STRIPE_WEBHOOK_SECRET,
        )
    except Exception as exc:
        log.warning("stripe.webhook.signature_invalid err=%s", exc)
        return HttpResponse(status=400)

    event_id = event.get("id")
    event_type = event.get("type")

    # Verrou idempotent ATOMIQUE : un autre worker recevant le même event
    # se met en file d'attente jusqu'à ce qu'on commit. Cela évite la fenêtre
    # entre `get_or_create` et `obj.processed = True`.
    obj, created = ProviderWebhookEvent.objects.select_for_update().get_or_create(
        provider="STRIPE",
        event_id=event_id,
        defaults={"event_type": event_type, "payload": event},
    )
    if not created and obj.processed:
        return HttpResponse(status=200)

    data_object = event["data"]["object"]

    if event_type == "checkout.session.completed":
        metadata = data_object.get("metadata") or {}
        tx_id = metadata.get("wallet_transaction_id")
        if tx_id:
            try:
                tx = WalletTransaction.objects.select_for_update().select_related("wallet").get(
                    id=tx_id, status="PENDING"
                )
                tx.status = "SUCCEEDED"
                tx.provider_reference = data_object.get("payment_intent") or data_object.get("id")
                tx.processed_at = timezone.now()
                tx.metadata = {**tx.metadata, "checkout_session": data_object}
                tx.save(update_fields=[
                    "status", "provider_reference", "processed_at", "metadata", "updated_at",
                ])

                # Crédit IDEMPOTENT par external_event_id = stripe event id.
                # Si le webhook arrive 2 fois, le ledger ne crédite qu'une fois.
                WalletService.credit_wallet(
                    wallet=tx.wallet,
                    amount=tx.amount,
                    tx_type="DEPOSIT",
                    provider="STRIPE",
                    provider_reference=tx.provider_reference,
                    description="Stripe deposit confirmed",
                    metadata={"source_tx_id": tx.id, "stripe_event_id": event_id},
                    external_event_id=f"stripe:{event_id}",
                )
            except WalletTransaction.DoesNotExist:
                log.info("stripe.webhook.tx_not_found tx_id=%s", tx_id)

    obj.processed = True
    obj.processed_at = timezone.now()
    obj.save(update_fields=["processed", "processed_at"])
    return HttpResponse(status=200)


# =============================================================================
# Adyen
# =============================================================================

def _adyen_compute_hmac(notification_dict: dict, hmac_key_hex: str) -> str:
    """
    Calcule le HMAC-SHA256 base64 d'un NotificationRequestItem Adyen.

    Source : https://docs.adyen.com/development-resources/webhooks/verify-hmac-signatures/
    Champs concaténés (dans cet ordre) séparés par ':' :
        pspReference, originalReference, merchantAccountCode, merchantReference,
        amount.value, amount.currency, eventCode, success
    """
    fields = [
        str(notification_dict.get("pspReference", "")),
        str(notification_dict.get("originalReference", "")),
        str(notification_dict.get("merchantAccountCode", "")),
        str(notification_dict.get("merchantReference", "")),
        str((notification_dict.get("amount") or {}).get("value", "")),
        str((notification_dict.get("amount") or {}).get("currency", "")),
        str(notification_dict.get("eventCode", "")),
        str(notification_dict.get("success", "")),
    ]
    # Échappement des caractères ':' et '\\' dans les valeurs
    escaped = [s.replace("\\", "\\\\").replace(":", "\\:") for s in fields]
    data_to_sign = ":".join(escaped)

    try:
        key_bytes = bytes.fromhex(hmac_key_hex)
    except ValueError:
        log.error("adyen.webhook.hmac_key_invalid_format")
        return ""

    digest = hmac.new(key_bytes, data_to_sign.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def _adyen_verify_signature(notification_dict: dict) -> bool:
    """
    Vérifie la signature HMAC du notification item.
    En mode dev sans clé configurée → on log et on accepte (pour ne pas casser
    l'environnement local). En prod, configure ADYEN_HMAC_KEY explicitement.
    """
    hmac_key = getattr(settings, "ADYEN_HMAC_KEY", "") or ""
    if not hmac_key:
        if not getattr(settings, "DEBUG", False):
            log.error("adyen.webhook.hmac_key_missing_in_prod — refusing webhook")
            return False
        log.warning("adyen.webhook.hmac_skipped_in_dev — configure ADYEN_HMAC_KEY")
        return True

    additional = notification_dict.get("additionalData") or {}
    received_sig = additional.get("hmacSignature")
    if not received_sig:
        log.warning("adyen.webhook.no_signature_in_payload")
        return False

    expected_sig = _adyen_compute_hmac(notification_dict, hmac_key)
    if not expected_sig:
        return False

    return hmac.compare_digest(expected_sig, received_sig)


@csrf_exempt
@require_POST
@transaction.atomic
def adyen_webhook(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponse(status=400)

    items = payload.get("notificationItems", [])
    for item in items:
        notif = item.get("NotificationRequestItem", {})

        # 1. VÉRIFIER LA SIGNATURE — indispensable pour ne pas accepter de
        # faux webhooks forgés par un attaquant.
        if not _adyen_verify_signature(notif):
            log.warning(
                "adyen.webhook.signature_rejected pspReference=%s",
                notif.get("pspReference"),
            )
            continue  # ignore l'item, on continue les autres

        event_code = notif.get("eventCode")
        success = str(notif.get("success", "false")).lower() == "true"
        psp_reference = notif.get("pspReference")
        merchant_reference = notif.get("merchantReference")

        # 2. Verrou idempotent atomique
        webhook_obj, created = ProviderWebhookEvent.objects.select_for_update().get_or_create(
            provider="ADYEN",
            event_id=psp_reference,
            defaults={"event_type": event_code, "payload": notif},
        )
        if not created and webhook_obj.processed:
            continue

        if event_code == "AUTHORISATION" and success:
            tx = WalletTransaction.objects.filter(
                provider="ADYEN",
                provider_reference=merchant_reference,
                status="PENDING",
            ).select_for_update().select_related("wallet").first()
            if tx:
                tx.status = "SUCCEEDED"
                tx.provider_reference = psp_reference
                tx.processed_at = timezone.now()
                tx.metadata = {**tx.metadata, "adyen_notification": notif}
                tx.save(update_fields=[
                    "status", "provider_reference", "processed_at", "metadata", "updated_at",
                ])
                WalletService.credit_wallet(
                    wallet=tx.wallet,
                    amount=tx.amount,
                    tx_type="DEPOSIT",
                    provider="ADYEN",
                    provider_reference=psp_reference,
                    description="Adyen deposit confirmed",
                    metadata={"source_tx_id": tx.id, "adyen_psp_reference": psp_reference},
                    external_event_id=f"adyen:{psp_reference}",
                )

        webhook_obj.processed = True
        webhook_obj.processed_at = timezone.now()
        webhook_obj.save(update_fields=["processed", "processed_at"])

    return JsonResponse({"notificationResponse": "[accepted]"})
