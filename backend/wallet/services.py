from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import hmac
import hashlib
import logging
import re
import uuid
from urllib.parse import quote

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Wallet, WalletTransaction, WithdrawalRequest, PaymentMethod
from .services_v2 import WalletLedgerService


log = logging.getLogger("lyneci.wallet.payments")


class PaymentGatewayError(RuntimeError):
    """Erreur de passerelle sans détail sensible destiné à l'utilisateur."""


class PaymentGatewayConfigurationError(PaymentGatewayError):
    pass


class PaymentGatewayValidationError(PaymentGatewayError):
    pass

try:
    import stripe
    if settings.STRIPE_SECRET_KEY:
        stripe.api_key = settings.STRIPE_SECRET_KEY
except Exception:  # pragma: no cover
    stripe = None


class WalletService:
    @staticmethod
    @transaction.atomic
    def confirm_deposit(
        *,
        transaction_id: int,
        provider: str,
        provider_reference: str,
        external_event_id: str,
        description: str,
        provider_payload: dict | None = None,
    ):
        """Crédite une transaction de dépôt une seule fois, sous verrou SQL."""
        tx = (
            WalletTransaction.objects.select_for_update()
            .select_related("wallet")
            .get(pk=transaction_id, provider=provider, tx_type="DEPOSIT")
        )

        if tx.status == "SUCCEEDED":
            return tx, False
        if tx.status != "PENDING":
            raise PaymentGatewayValidationError(
                f"Transaction non confirmable dans l'état {tx.status}."
            )
        if tx.currency.upper() != tx.wallet.currency.upper():
            raise PaymentGatewayValidationError(
                "La devise du dépôt ne correspond pas à celle du wallet."
            )

        WalletLedgerService.credit(
            wallet_id=tx.wallet_id,
            amount=tx.amount,
            external_event_id=external_event_id,
            transaction_obj=tx,
            description=description,
            metadata={
                "provider": provider,
                "provider_reference": provider_reference,
            },
        )

        tx.status = "SUCCEEDED"
        tx.provider_reference = provider_reference
        tx.processed_at = timezone.now()
        tx.metadata = {
            **(tx.metadata or {}),
            "provider_confirmation": provider_payload or {},
        }
        tx.save(update_fields=[
            "status",
            "provider_reference",
            "processed_at",
            "metadata",
            "updated_at",
        ])
        return tx, True

    @staticmethod
    @transaction.atomic
    def credit_wallet(wallet: Wallet, amount: Decimal, tx_type="DEPOSIT", provider=None, provider_reference=None, description="", metadata=None):
        tx = WalletTransaction.objects.create(
            wallet=wallet,
            tx_type=tx_type,
            status="SUCCEEDED",
            amount=amount,
            currency=wallet.currency,
            provider=provider,
            provider_reference=provider_reference,
            description=description,
            metadata=metadata or {},
            processed_at=timezone.now(),
        )
        wallet.available_balance = (wallet.available_balance or Decimal("0.00")) + amount
        if tx_type == "DEPOSIT":
            wallet.total_deposited = (wallet.total_deposited or Decimal("0.00")) + amount
        wallet.save(update_fields=["available_balance", "total_deposited", "updated_at"])
        return tx

    @staticmethod
    @transaction.atomic
    def lock_funds_for_withdrawal(wallet: Wallet, amount: Decimal, destination_type="BANK", destination_masked=""):
        tx = WalletTransaction.objects.create(
            wallet=wallet,
            tx_type="WITHDRAWAL",
            status="PENDING",
            amount=amount,
            currency=wallet.currency,
            provider="MANUAL",
            description="Withdrawal request created",
        )
        WalletLedgerService.lock(
            wallet_id=wallet.id,
            amount=amount,
            external_event_id=f"withdrawal-lock:{tx.id}",
            transaction_obj=tx,
            description="Fonds verrouillés pour demande de retrait",
        )

        wd = WithdrawalRequest.objects.create(
            wallet=wallet,
            amount=amount,
            currency=wallet.currency,
            destination_type=destination_type,
            destination_masked=destination_masked,
            status="PENDING",
            metadata={"wallet_transaction_id": tx.id},
        )
        return wd, tx

    @staticmethod
    def _get_linked_transaction(withdrawal: WithdrawalRequest):
        """
        Retourne la WalletTransaction liée en priorité via l'ID stocké
        dans les métadonnées, pour éviter de matcher par montant (ambigu
        quand plusieurs retraits ont le même montant).
        """
        tx_id = (withdrawal.metadata or {}).get("wallet_transaction_id")
        if tx_id:
            tx = WalletTransaction.objects.filter(
                pk=tx_id,
                wallet=withdrawal.wallet,
                tx_type="WITHDRAWAL",
            ).first()
            if tx:
                return tx
        # Fallback : on prend la transaction PENDING la plus récente du même montant
        return WalletTransaction.objects.filter(
            wallet=withdrawal.wallet,
            tx_type="WITHDRAWAL",
            amount=withdrawal.amount,
            status="PENDING",
        ).order_by("-created_at").first()

    @staticmethod
    @transaction.atomic
    def mark_withdrawal_paid(withdrawal: WithdrawalRequest, provider=None, provider_reference=None):
        tx = WalletService._get_linked_transaction(withdrawal)
        WalletLedgerService.unlock(
            wallet_id=withdrawal.wallet_id,
            amount=withdrawal.amount,
            external_event_id=f"withdrawal-paid:{withdrawal.id}",
            transaction_obj=tx,
            to_available=False,
            description="Retrait payé",
            metadata={
                "provider": provider or withdrawal.provider,
                "provider_reference": provider_reference,
            },
        )

        withdrawal.status = "PAID"
        withdrawal.provider = provider or withdrawal.provider
        withdrawal.provider_reference = provider_reference or withdrawal.provider_reference
        withdrawal.paid_at = timezone.now()
        withdrawal.save(update_fields=["status", "provider", "provider_reference", "paid_at", "updated_at"])

        if tx and tx.status == "PENDING":
            tx.status = "SUCCEEDED"
            tx.provider = provider or "MANUAL"
            tx.provider_reference = provider_reference
            tx.processed_at = timezone.now()
            tx.save(update_fields=["status", "provider", "provider_reference", "processed_at", "updated_at"])

        return withdrawal

    @staticmethod
    @transaction.atomic
    def reject_withdrawal(withdrawal: WithdrawalRequest, reason=""):
        tx = WalletService._get_linked_transaction(withdrawal)
        WalletLedgerService.unlock(
            wallet_id=withdrawal.wallet_id,
            amount=withdrawal.amount,
            external_event_id=f"withdrawal-rejected:{withdrawal.id}",
            transaction_obj=tx,
            to_available=True,
            description="Retrait rejeté — fonds restitués",
            metadata={"reason": reason},
        )

        withdrawal.status = "REJECTED"
        withdrawal.failure_reason = reason
        withdrawal.reviewed_at = timezone.now()
        withdrawal.save(update_fields=["status", "failure_reason", "reviewed_at", "updated_at"])

        if tx and tx.status == "PENDING":
            tx.status = "FAILED"
            tx.description = reason
            tx.processed_at = timezone.now()
            tx.save(update_fields=["status", "description", "processed_at", "updated_at"])

        return withdrawal


class StripeWalletService:
    @staticmethod
    def create_deposit_checkout_session(user, wallet: Wallet, amount: Decimal, currency="usd"):
        if stripe is None:
            raise RuntimeError("Stripe n'est pas configuré")

        tx = WalletTransaction.objects.create(
            wallet=wallet,
            tx_type="DEPOSIT",
            status="PENDING",
            amount=amount,
            currency=currency.upper(),
            provider="STRIPE",
            description="Stripe deposit session",
        )

        session = stripe.checkout.Session.create(
            mode="payment",
            success_url=f"{settings.SITE_BASE_URL}/wallet/deposit/success/?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{settings.SITE_BASE_URL}/wallet/deposit/cancel/",
            client_reference_id=str(user.id),
            metadata={
                "wallet_transaction_id": str(tx.id),
                "user_id": str(user.id),
            },
            line_items=[{
                "price_data": {
                    "currency": currency.lower(),
                    "product_data": {"name": "Lyneci Wallet Deposit"},
                    "unit_amount": int(amount * 100),
                },
                "quantity": 1,
            }],
        )

        tx.provider_session_id = session.id
        tx.metadata = {"checkout_session_url": session.url}
        tx.save(update_fields=["provider_session_id", "metadata", "updated_at"])
        return session, tx


class AdyenWalletService:
    @staticmethod
    def base_url():
        if settings.ADYEN_ENV.upper() == "LIVE":
            return "https://checkout-live.adyen.com"
        return "https://checkout-test.adyen.com"

    @classmethod
    def create_deposit_session(cls, user, wallet: Wallet, amount: Decimal, currency="USD", reference_prefix="LYNECI-DEP"):
        if not settings.ADYEN_API_KEY or not settings.ADYEN_MERCHANT_ACCOUNT:
            raise RuntimeError("Adyen n'est pas configuré")

        tx = WalletTransaction.objects.create(
            wallet=wallet,
            tx_type="DEPOSIT",
            status="PENDING",
            amount=amount,
            currency=currency.upper(),
            provider="ADYEN",
            description="Adyen deposit session",
        )

        reference = f"{reference_prefix}-{tx.id}"
        payload = {
            "amount": {
                "currency": currency.upper(),
                "value": int(amount * 100),
            },
            "reference": reference,
            "merchantAccount": settings.ADYEN_MERCHANT_ACCOUNT,
            "returnUrl": f"{settings.SITE_BASE_URL}/wallet/deposit/success/?provider=adyen&tx={tx.id}",
            "countryCode": "US",
            "shopperReference": str(user.id),
            "shopperEmail": getattr(user, "email", "") or "",
        }

        response = requests.post(
            f"{cls.base_url()}/v71/sessions",
            headers={
                "X-API-Key": settings.ADYEN_API_KEY,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        tx.provider_reference = reference
        tx.provider_session_id = data.get("id")
        tx.metadata = data
        tx.save(update_fields=["provider_reference", "provider_session_id", "metadata", "updated_at"])
        return data, tx

    @staticmethod
    def verify_hmac(payload_item: dict) -> bool:
        # MVP simplifié : à compléter selon configuration Adyen HMAC
        return True


class PaystackWalletService:
    PROVIDER = "PAYSTACK"
    REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9.=-]{1,255}$")
    MINIMUM_AMOUNTS = {
        "NGN": Decimal("50.00"),
        "USD": Decimal("2.00"),
        "GHS": Decimal("0.10"),
        "ZAR": Decimal("1.00"),
        "KES": Decimal("3.00"),
        "XOF": Decimal("1.00"),
    }
    FINAL_FAILURE_STATUSES = {"abandoned", "failed", "reversed"}

    @classmethod
    def _secret_key(cls) -> str:
        secret = getattr(settings, "PAYSTACK_SECRET_KEY", "") or ""
        if not secret:
            raise PaymentGatewayConfigurationError("Paystack n'est pas configuré.")
        return secret

    @classmethod
    def _supported_currencies(cls) -> set[str]:
        configured = getattr(
            settings,
            "PAYSTACK_SUPPORTED_CURRENCIES",
            ["XOF", "NGN", "GHS", "KES", "ZAR", "USD"],
        )
        if isinstance(configured, str):
            configured = configured.split(",")
        return {str(currency).upper() for currency in configured}

    @classmethod
    def amount_to_subunit(cls, amount, currency: str) -> int:
        currency = str(currency).upper()
        if currency not in cls._supported_currencies():
            raise PaymentGatewayValidationError(
                f"La devise {currency} n'est pas activée pour Paystack."
            )

        try:
            normalized = Decimal(str(amount))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise PaymentGatewayValidationError("Montant Paystack invalide.") from exc
        if not normalized.is_finite():
            raise PaymentGatewayValidationError("Montant Paystack invalide.")

        minimum = cls.MINIMUM_AMOUNTS.get(currency, Decimal("0.01"))
        if normalized < minimum:
            raise PaymentGatewayValidationError(
                f"Le montant minimum Paystack en {currency} est {minimum}."
            )
        if currency == "XOF" and normalized != normalized.to_integral_value():
            raise PaymentGatewayValidationError(
                "Paystack n'accepte pas de fraction pour les paiements XOF."
            )

        subunit = normalized * Decimal("100")
        if subunit != subunit.to_integral_value():
            raise PaymentGatewayValidationError("Le montant contient trop de décimales.")
        return int(subunit)

    @classmethod
    def _request(cls, method: str, path: str, *, json_payload=None) -> dict:
        base_url = getattr(settings, "PAYSTACK_API_BASE_URL", "https://api.paystack.co")
        if not getattr(settings, "DEBUG", False) and not str(base_url).startswith("https://"):
            raise PaymentGatewayConfigurationError(
                "L'API Paystack doit être appelée en HTTPS."
            )
        timeout = getattr(settings, "PAYSTACK_TIMEOUT_SECONDS", 10)
        url = f"{str(base_url).rstrip('/')}/{path.lstrip('/')}"
        try:
            response = requests.request(
                method,
                url,
                headers={
                    "Authorization": f"Bearer {cls._secret_key()}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=json_payload,
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            log.warning(
                "paystack.api.request_failed method=%s path=%s error=%s",
                method,
                path,
                type(exc).__name__,
            )
            raise PaymentGatewayError("Paystack est temporairement indisponible.") from exc
        except (TypeError, ValueError) as exc:
            log.warning("paystack.api.invalid_json method=%s path=%s", method, path)
            raise PaymentGatewayError("Réponse Paystack invalide.") from exc

        if not isinstance(payload, dict) or payload.get("status") is not True:
            log.warning("paystack.api.rejected method=%s path=%s", method, path)
            raise PaymentGatewayError("Paystack a refusé la demande.")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise PaymentGatewayError("Réponse Paystack incomplète.")
        return data

    @staticmethod
    def _metadata_dict(data: dict) -> dict:
        metadata = data.get("metadata") or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (TypeError, ValueError):
                return {}
        return metadata if isinstance(metadata, dict) else {}

    @classmethod
    def sanitized_transaction_payload(cls, data: dict) -> dict:
        customer = data.get("customer") or {}
        return {
            "id": data.get("id"),
            "status": data.get("status"),
            "reference": data.get("reference"),
            "amount": data.get("amount"),
            "currency": data.get("currency"),
            "channel": data.get("channel"),
            "paid_at": data.get("paid_at") or data.get("paidAt"),
            "fees": data.get("fees"),
            "metadata": cls._metadata_dict(data),
            "customer": {
                "customer_code": customer.get("customer_code") if isinstance(customer, dict) else None,
                "email": customer.get("email") if isinstance(customer, dict) else None,
            },
        }

    @classmethod
    def create_deposit_checkout(cls, *, user, wallet: Wallet, amount, currency: str):
        cls._secret_key()
        email = (getattr(user, "email", "") or "").strip()
        if not email:
            raise PaymentGatewayValidationError(
                "Une adresse e-mail est requise pour payer avec Paystack."
            )

        currency = str(currency).upper()
        amount = Decimal(str(amount))
        subunit_amount = cls.amount_to_subunit(amount, currency)
        if wallet.currency.upper() != currency:
            raise PaymentGatewayValidationError(
                "La devise du dépôt doit être identique à celle du wallet."
            )
        site_base_url = settings.SITE_BASE_URL.rstrip("/")
        if not getattr(settings, "DEBUG", False) and not site_base_url.startswith("https://"):
            raise PaymentGatewayConfigurationError(
                "Le callback Paystack doit utiliser HTTPS en production."
            )

        tx = WalletTransaction.objects.create(
            wallet=wallet,
            tx_type="DEPOSIT",
            status="PENDING",
            amount=amount,
            currency=currency,
            provider=cls.PROVIDER,
            description="Paystack deposit checkout",
        )
        reference = f"LYNECI-DEP-{tx.id}-{uuid.uuid4().hex[:16]}"
        tx.provider_reference = reference
        tx.save(update_fields=["provider_reference", "updated_at"])

        callback_url = (
            f"{site_base_url}/wallet/deposit/success/"
            f"?provider=paystack&reference={reference}"
        )
        request_metadata = {
            "wallet_transaction_id": str(tx.id),
            "wallet_id": str(wallet.id),
            "user_id": str(user.id),
        }
        try:
            data = cls._request(
                "POST",
                "/transaction/initialize",
                json_payload={
                    "email": email,
                    "amount": str(subunit_amount),
                    "currency": currency,
                    "reference": reference,
                    "callback_url": callback_url,
                    "metadata": json.dumps(request_metadata, separators=(",", ":")),
                },
            )
            if data.get("reference") != reference:
                raise PaymentGatewayError("Référence Paystack incohérente.")
            authorization_url = data.get("authorization_url")
            access_code = data.get("access_code")
            if not authorization_url or not access_code:
                raise PaymentGatewayError("Session Paystack incomplète.")
        except PaymentGatewayError:
            WalletTransaction.objects.filter(pk=tx.pk, status="PENDING").update(
                status="FAILED",
                processed_at=timezone.now(),
                metadata={"paystack_initialization": "failed"},
            )
            raise

        tx.provider_session_id = str(access_code)
        tx.metadata = {
            "authorization_url": str(authorization_url),
            "paystack_reference": reference,
        }
        tx.save(update_fields=["provider_session_id", "metadata", "updated_at"])
        return data, tx

    @classmethod
    def verify_transaction(cls, reference: str) -> dict:
        reference = str(reference or "").strip()
        if not cls.REFERENCE_PATTERN.fullmatch(reference):
            raise PaymentGatewayValidationError("Référence Paystack invalide.")
        return cls._request("GET", f"/transaction/verify/{quote(reference, safe='')}")

    @classmethod
    def _validate_success_payload(cls, tx: WalletTransaction, data: dict):
        reference = str(data.get("reference") or "")
        if reference != tx.provider_reference:
            raise PaymentGatewayValidationError("Référence Paystack incohérente.")
        if str(data.get("status") or "").lower() != "success":
            raise PaymentGatewayValidationError("La transaction Paystack n'est pas réussie.")
        if str(data.get("currency") or "").upper() != tx.currency.upper():
            raise PaymentGatewayValidationError("Devise Paystack incohérente.")

        amount = data.get("amount")
        if isinstance(amount, bool):
            raise PaymentGatewayValidationError("Montant Paystack invalide.")
        try:
            received_subunit = int(amount)
        except (TypeError, ValueError) as exc:
            raise PaymentGatewayValidationError("Montant Paystack invalide.") from exc
        if received_subunit != cls.amount_to_subunit(tx.amount, tx.currency):
            raise PaymentGatewayValidationError("Montant Paystack incohérent.")

        metadata_tx_id = cls._metadata_dict(data).get("wallet_transaction_id")
        if metadata_tx_id and str(metadata_tx_id) != str(tx.id):
            raise PaymentGatewayValidationError("Transaction wallet incohérente.")

    @classmethod
    def apply_success_payload(cls, *, data: dict, external_event_id: str):
        reference = str(data.get("reference") or "").strip()
        if not cls.REFERENCE_PATTERN.fullmatch(reference):
            raise PaymentGatewayValidationError("Référence Paystack invalide.")

        tx = (
            WalletTransaction.objects.select_related("wallet")
            .filter(provider=cls.PROVIDER, provider_reference=reference, tx_type="DEPOSIT")
            .first()
        )
        if not tx:
            raise WalletTransaction.DoesNotExist
        cls._validate_success_payload(tx, data)
        return WalletService.confirm_deposit(
            transaction_id=tx.id,
            provider=cls.PROVIDER,
            provider_reference=reference,
            external_event_id=external_event_id,
            description="Paystack deposit confirmed",
            provider_payload=cls.sanitized_transaction_payload(data),
        )

    @classmethod
    def verify_and_confirm(cls, *, reference: str, wallet_id: int):
        tx = WalletTransaction.objects.filter(
            wallet_id=wallet_id,
            provider=cls.PROVIDER,
            provider_reference=reference,
            tx_type="DEPOSIT",
        ).first()
        if not tx:
            raise WalletTransaction.DoesNotExist
        if tx.status == "SUCCEEDED":
            return tx, "succeeded"

        data = cls.verify_transaction(reference)
        provider_status = str(data.get("status") or "").lower()
        if provider_status == "success":
            provider_id = data.get("id") or reference
            confirmed_tx, _ = cls.apply_success_payload(
                data=data,
                external_event_id=f"paystack:verify:{provider_id}",
            )
            return confirmed_tx, "succeeded"

        if provider_status in cls.FINAL_FAILURE_STATUSES:
            WalletTransaction.objects.filter(pk=tx.pk, status="PENDING").update(
                status="FAILED",
                processed_at=timezone.now(),
                metadata={
                    **(tx.metadata or {}),
                    "paystack_status": provider_status,
                },
            )
            tx.refresh_from_db()
            return tx, "succeeded" if tx.status == "SUCCEEDED" else "failed"
        return tx, "pending"


class PayoutService:
    @staticmethod
    def submit_withdrawal(withdrawal: WithdrawalRequest):
        """
        MVP: laisse la demande en review / approved.
        Brancher ici Adyen Transfers / payout ou un partenaire bancaire selon ton contrat.
        """
        withdrawal.status = "UNDER_REVIEW"
        withdrawal.save(update_fields=["status", "updated_at"])
        return withdrawal
