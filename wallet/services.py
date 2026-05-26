from decimal import Decimal
import json
import hmac
import hashlib

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Wallet, WalletTransaction, WithdrawalRequest, PaymentMethod

try:
    import stripe
    if settings.STRIPE_SECRET_KEY:
        stripe.api_key = settings.STRIPE_SECRET_KEY
except Exception:  # pragma: no cover
    stripe = None


class WalletService:
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
        if wallet.available_balance < amount:
            raise ValueError("Solde insuffisant")
        wallet.available_balance -= amount
        wallet.locked_balance += amount
        wallet.save(update_fields=["available_balance", "locked_balance", "updated_at"])

        tx = WalletTransaction.objects.create(
            wallet=wallet,
            tx_type="WITHDRAWAL",
            status="PENDING",
            amount=amount,
            currency=wallet.currency,
            provider="MANUAL",
            description="Withdrawal request created",
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
        wallet = withdrawal.wallet
        if wallet.locked_balance < withdrawal.amount:
            raise ValueError("Locked balance incoherent")
        wallet.locked_balance -= withdrawal.amount
        wallet.total_withdrawn = (wallet.total_withdrawn or Decimal("0.00")) + withdrawal.amount
        wallet.save(update_fields=["locked_balance", "total_withdrawn", "updated_at"])

        withdrawal.status = "PAID"
        withdrawal.provider = provider or withdrawal.provider
        withdrawal.provider_reference = provider_reference or withdrawal.provider_reference
        withdrawal.paid_at = timezone.now()
        withdrawal.save(update_fields=["status", "provider", "provider_reference", "paid_at", "updated_at"])

        # Ciblage précis de la transaction liée (par ID) plutôt que par montant
        tx = WalletService._get_linked_transaction(withdrawal)
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
        wallet = withdrawal.wallet
        if wallet.locked_balance < withdrawal.amount:
            raise ValueError("Locked balance incoherent")
        wallet.locked_balance -= withdrawal.amount
        wallet.available_balance += withdrawal.amount
        wallet.save(update_fields=["locked_balance", "available_balance", "updated_at"])

        withdrawal.status = "REJECTED"
        withdrawal.failure_reason = reason
        withdrawal.reviewed_at = timezone.now()
        withdrawal.save(update_fields=["status", "failure_reason", "reviewed_at", "updated_at"])

        # Ciblage précis de la transaction liée (par ID) plutôt que par montant
        tx = WalletService._get_linked_transaction(withdrawal)
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
                    "product_data": {"name": "LeoTrade Wallet Deposit"},
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
    def create_deposit_session(cls, user, wallet: Wallet, amount: Decimal, currency="USD", reference_prefix="LEOTRADE-DEP"):
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