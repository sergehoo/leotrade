import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
import requests
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from wallet.models import (
    ProviderWebhookEvent,
    Wallet,
    WalletLedgerEntry,
    WalletTransaction,
)
from wallet.services import (
    PaymentGatewayConfigurationError,
    PaymentGatewayError,
    PaystackWalletService,
)


User = get_user_model()
PAYSTACK_SETTINGS = {
    "PAYSTACK_SECRET_KEY": "sk_test_lyneci",
    "PAYSTACK_API_BASE_URL": "https://api.paystack.co",
    "PAYSTACK_TIMEOUT_SECONDS": 5,
    "PAYSTACK_SUPPORTED_CURRENCIES": ["USD", "XOF"],
    "SITE_BASE_URL": "https://lyneci.example",
}


def _user_and_wallet(username="paystack-user"):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="test-password",
    )
    wallet = Wallet.objects.get(user=user)
    Wallet.objects.filter(pk=wallet.pk).update(
        currency="USD",
        available_balance=Decimal("0.00"),
        total_deposited=Decimal("0.00"),
    )
    wallet.refresh_from_db()
    return user, wallet


def _response(payload, status_code=200):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
    else:
        response.raise_for_status.return_value = None
    return response


def _pending_transaction(wallet, reference="LYNECI-DEP-TEST-001", amount="10.00"):
    return WalletTransaction.objects.create(
        wallet=wallet,
        tx_type="DEPOSIT",
        status="PENDING",
        amount=Decimal(amount),
        currency=wallet.currency,
        provider="PAYSTACK",
        provider_reference=reference,
        description="Paystack test deposit",
    )


def _success_payload(tx, *, provider_id=9001, amount=None):
    return {
        "event": "charge.success",
        "data": {
            "id": provider_id,
            "status": "success",
            "reference": tx.provider_reference,
            "amount": amount if amount is not None else int(tx.amount * 100),
            "currency": tx.currency,
            "channel": "card",
            "paid_at": "2026-07-21T12:00:00.000Z",
            "metadata": {"wallet_transaction_id": str(tx.id)},
            "customer": {
                "email": tx.wallet.user.email,
                "customer_code": "CUS_test",
            },
            "authorization": {
                "authorization_code": "AUTH_must_not_be_persisted",
                "last4": "4081",
            },
        },
    }


def _signature(body: bytes, secret=PAYSTACK_SETTINGS["PAYSTACK_SECRET_KEY"]):
    return hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()


@pytest.mark.django_db
@override_settings(**PAYSTACK_SETTINGS)
def test_paystack_checkout_initializes_server_side_and_redirects(client):
    user, wallet = _user_and_wallet()
    client.force_login(user)
    captured = {}

    def initialize(method, url, **kwargs):
        captured.update({"method": method, "url": url, **kwargs})
        reference = kwargs["json"]["reference"]
        return _response({
            "status": True,
            "data": {
                "authorization_url": "https://checkout.paystack.com/access-code",
                "access_code": "access-code",
                "reference": reference,
            },
        })

    with patch("wallet.services.requests.request", side_effect=initialize):
        response = client.post(reverse("wallet-deposit"), {
            "amount": "12.34",
            "currency": "USD",
            "provider": "PAYSTACK",
        })

    assert response.status_code == 303
    assert response["Location"] == "https://checkout.paystack.com/access-code"
    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.paystack.co/transaction/initialize"
    assert captured["headers"]["Authorization"] == "Bearer sk_test_lyneci"
    assert captured["json"]["amount"] == "1234"
    assert captured["json"]["currency"] == "USD"
    assert captured["json"]["callback_url"].startswith(
        "https://lyneci.example/wallet/deposit/success/"
    )

    tx = WalletTransaction.objects.get(wallet=wallet, provider="PAYSTACK")
    metadata = json.loads(captured["json"]["metadata"])
    assert metadata["wallet_transaction_id"] == str(tx.id)
    assert tx.status == "PENDING"
    assert tx.provider_session_id == "access-code"


@pytest.mark.django_db
@override_settings(PAYSTACK_SECRET_KEY="", PAYSTACK_SUPPORTED_CURRENCIES=["USD"])
def test_paystack_checkout_fails_closed_without_secret():
    user, wallet = _user_and_wallet()
    with pytest.raises(PaymentGatewayConfigurationError):
        PaystackWalletService.create_deposit_checkout(
            user=user,
            wallet=wallet,
            amount=Decimal("10.00"),
            currency="USD",
        )
    assert not WalletTransaction.objects.filter(provider="PAYSTACK").exists()


@pytest.mark.django_db
@override_settings(**PAYSTACK_SETTINGS)
def test_paystack_api_failure_marks_pending_transaction_failed():
    user, wallet = _user_and_wallet()
    with patch(
        "wallet.services.requests.request",
        side_effect=requests.Timeout("provider timeout"),
    ):
        with pytest.raises(PaymentGatewayError):
            PaystackWalletService.create_deposit_checkout(
                user=user,
                wallet=wallet,
                amount=Decimal("10.00"),
                currency="USD",
            )

    tx = WalletTransaction.objects.get(provider="PAYSTACK")
    assert tx.status == "FAILED"
    assert "provider timeout" not in json.dumps(tx.metadata)


@pytest.mark.django_db
@override_settings(**PAYSTACK_SETTINGS)
def test_paystack_webhook_rejects_invalid_signature(client):
    _, wallet = _user_and_wallet()
    tx = _pending_transaction(wallet)
    body = json.dumps(_success_payload(tx), separators=(",", ":")).encode()

    response = client.post(
        reverse("paystack-webhook"),
        data=body,
        content_type="application/json",
        HTTP_X_PAYSTACK_SIGNATURE="invalid",
    )

    assert response.status_code == 400
    tx.refresh_from_db()
    wallet.refresh_from_db()
    assert tx.status == "PENDING"
    assert wallet.available_balance == Decimal("0.00")
    assert not ProviderWebhookEvent.objects.filter(provider="PAYSTACK").exists()


@pytest.mark.django_db
@override_settings(**PAYSTACK_SETTINGS)
def test_paystack_webhook_credits_once_and_strips_card_data(client):
    _, wallet = _user_and_wallet()
    tx = _pending_transaction(wallet)
    payload = _success_payload(tx)
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = _signature(body)

    first = client.post(
        reverse("paystack-webhook"),
        data=body,
        content_type="application/json",
        HTTP_X_PAYSTACK_SIGNATURE=signature,
    )
    second = client.post(
        reverse("paystack-webhook"),
        data=body,
        content_type="application/json",
        HTTP_X_PAYSTACK_SIGNATURE=signature,
    )

    assert first.status_code == second.status_code == 200
    tx.refresh_from_db()
    wallet.refresh_from_db()
    assert tx.status == "SUCCEEDED"
    assert wallet.available_balance == Decimal("10.00")
    assert wallet.total_deposited == Decimal("10.00")
    assert WalletLedgerEntry.objects.filter(wallet=wallet, entry_type="CREDIT").count() == 1
    event = ProviderWebhookEvent.objects.get(provider="PAYSTACK")
    assert event.processed is True
    assert "authorization" not in json.dumps(event.payload).lower()
    assert "AUTH_must_not_be_persisted" not in json.dumps(tx.metadata)


@pytest.mark.django_db
@override_settings(**PAYSTACK_SETTINGS)
def test_paystack_webhook_never_credits_wrong_amount(client):
    _, wallet = _user_and_wallet()
    tx = _pending_transaction(wallet)
    body = json.dumps(
        _success_payload(tx, amount=999999),
        separators=(",", ":"),
    ).encode()

    response = client.post(
        reverse("paystack-webhook"),
        data=body,
        content_type="application/json",
        HTTP_X_PAYSTACK_SIGNATURE=_signature(body),
    )

    assert response.status_code == 200
    tx.refresh_from_db()
    wallet.refresh_from_db()
    assert tx.status == "PENDING"
    assert wallet.available_balance == Decimal("0.00")
    assert not WalletLedgerEntry.objects.filter(wallet=wallet).exists()


@pytest.mark.django_db
@override_settings(**PAYSTACK_SETTINGS)
def test_paystack_callback_verifies_then_confirms_payment(client):
    user, wallet = _user_and_wallet()
    tx = _pending_transaction(wallet)
    client.force_login(user)
    provider_data = _success_payload(tx)["data"]

    with patch(
        "wallet.services.requests.request",
        return_value=_response({"status": True, "data": provider_data}),
    ) as request_mock:
        response = client.get(
            reverse("wallet-deposit-success"),
            {"provider": "paystack", "reference": tx.provider_reference},
        )

    assert response.status_code == 200
    assert response.context["payment_status"] == "succeeded"
    request_mock.assert_called_once()
    tx.refresh_from_db()
    wallet.refresh_from_db()
    assert tx.status == "SUCCEEDED"
    assert wallet.available_balance == Decimal("10.00")


@pytest.mark.django_db
@override_settings(**PAYSTACK_SETTINGS)
def test_paystack_callback_cannot_confirm_another_users_transaction(client):
    user, wallet = _user_and_wallet("owner-a")
    _, other_wallet = _user_and_wallet("owner-b")
    other_tx = _pending_transaction(other_wallet, reference="LYNECI-DEP-OTHER-001")
    client.force_login(user)

    with patch("wallet.services.requests.request") as request_mock:
        response = client.get(
            reverse("wallet-deposit-success"),
            {"provider": "paystack", "reference": other_tx.provider_reference},
        )

    assert response.status_code == 200
    assert response.context["payment_status"] == "unknown"
    request_mock.assert_not_called()
    wallet.refresh_from_db()
    other_wallet.refresh_from_db()
    assert wallet.available_balance == Decimal("0.00")
    assert other_wallet.available_balance == Decimal("0.00")
