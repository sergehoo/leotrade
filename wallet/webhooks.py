"""
wallet/webhooks.py
==================

Webhooks de paiement Stripe + Adyen + Paystack.

Garanties :
  - Signature broker validée (Stripe via SDK, Adyen via HMAC-SHA256)
  - Idempotence atomique : `select_for_update()` sur `ProviderWebhookEvent`
    pour éviter les doubles crédits sur retries simultanés
  - Crédit wallet via `WalletService.confirm_deposit()` et le ledger atomique
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
from .services import (
    PaymentGatewayValidationError,
    PaystackWalletService,
    WalletService,
)

try:
    import stripe
    if settings.STRIPE_SECRET_KEY:
        stripe.api_key = settings.STRIPE_SECRET_KEY
except Exception:  # pragma: no cover
    stripe = None


log = logging.getLogger("lyneci.wallet.webhooks")


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
                provider_reference = data_object.get("payment_intent") or data_object.get("id")
                WalletService.confirm_deposit(
                    transaction_id=tx.id,
                    provider="STRIPE",
                    provider_reference=provider_reference,
                    external_event_id=f"stripe:{event_id}",
                    description="Stripe deposit confirmed",
                    provider_payload={
                        "id": data_object.get("id"),
                        "payment_intent": data_object.get("payment_intent"),
                        "payment_status": data_object.get("payment_status"),
                    },
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
                WalletService.confirm_deposit(
                    transaction_id=tx.id,
                    provider="ADYEN",
                    provider_reference=psp_reference,
                    external_event_id=f"adyen:{psp_reference}",
                    description="Adyen deposit confirmed",
                    provider_payload={
                        "psp_reference": psp_reference,
                        "merchant_reference": merchant_reference,
                        "event_code": event_code,
                        "success": success,
                    },
                )

        webhook_obj.processed = True
        webhook_obj.processed_at = timezone.now()
        webhook_obj.save(update_fields=["processed", "processed_at"])

    return JsonResponse({"notificationResponse": "[accepted]"})


# =============================================================================
# Paystack
# =============================================================================

@csrf_exempt
@require_POST
def paystack_webhook(request):
    secret = getattr(settings, "PAYSTACK_SECRET_KEY", "") or ""
    if not secret:
        log.error("paystack.webhook.secret_missing")
        return HttpResponse(status=503)

    received_signature = request.META.get("HTTP_X_PAYSTACK_SIGNATURE", "")
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        request.body,
        hashlib.sha512,
    ).hexdigest()
    if not received_signature or not hmac.compare_digest(
        expected_signature,
        received_signature,
    ):
        log.warning("paystack.webhook.signature_invalid")
        return HttpResponse(status=400)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return HttpResponse(status=400)

    event_type = payload.get("event") if isinstance(payload, dict) else None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(event_type, str) or not isinstance(data, dict):
        return HttpResponse(status=400)

    reference = str(data.get("reference") or "").strip()
    provider_transaction_id = data.get("id")
    if event_type == "charge.success" and not reference:
        return HttpResponse(status=400)

    event_identity = provider_transaction_id or reference
    if not event_identity:
        return HttpResponse(status=200)
    event_id = f"{event_type}:{event_identity}"
    sanitized_payload = {
        "event": event_type,
        "data": PaystackWalletService.sanitized_transaction_payload(data),
    }

    with transaction.atomic():
        webhook_obj, created = ProviderWebhookEvent.objects.select_for_update().get_or_create(
            provider="PAYSTACK",
            event_id=event_id,
            defaults={"event_type": event_type, "payload": sanitized_payload},
        )
        if not created and webhook_obj.processed:
            return HttpResponse(status=200)

        if event_type == "charge.success":
            try:
                PaystackWalletService.apply_success_payload(
                    data=data,
                    external_event_id=f"paystack:webhook:{event_id}",
                )
            except WalletTransaction.DoesNotExist:
                log.info("paystack.webhook.tx_not_found reference=%s", reference)
            except PaymentGatewayValidationError as exc:
                log.warning(
                    "paystack.webhook.payload_rejected reference=%s reason=%s",
                    reference,
                    exc,
                )

        webhook_obj.processed = True
        webhook_obj.processed_at = timezone.now()
        webhook_obj.save(update_fields=["processed", "processed_at"])

    return HttpResponse(status=200)
