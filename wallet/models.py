from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import F
from django.utils import timezone


class Wallet(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wallet",
    )
    currency = models.CharField(max_length=10, default="USD")
    available_balance = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    locked_balance = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    total_deposited = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    total_withdrawn = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def can_withdraw(self):
        return self.is_active and self.available_balance > 0

    @property
    def total_balance(self):
        return (self.available_balance or Decimal("0.00")) + (self.locked_balance or Decimal("0.00"))

    def has_sufficient_balance(self, amount):
        return self.available_balance >= amount


    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["user"], name="uniq_wallet_per_user")
        ]

    def __str__(self):
        return f"Wallet {self.user}"


class PaymentMethod(models.Model):
    PROVIDER_CHOICES = [
        ("STRIPE", "Stripe"),
        ("ADYEN", "Adyen"),
        ("CINETPAY", "CinetPay"),
        ("PAYSTACK", "Paystack"),
        ("ORANGE_MONEY", "Orange Money"),
        ("MTN_MOMO", "MTN MoMo"),
        ("WAVE", "Wave"),
        ("MANUAL", "Manual"),
    ]
    METHOD_TYPE_CHOICES = [
        ("CARD", "Card"),
        ("BANK", "Bank"),
        ("MOBILE_MONEY", "Mobile Money"),
        ("WALLET", "Wallet"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wallet_payment_methods")
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    method_type = models.CharField(max_length=20, choices=METHOD_TYPE_CHOICES, default="CARD")
    provider_customer_id = models.CharField(max_length=255, blank=True, null=True)
    provider_payment_method_id = models.CharField(max_length=255, blank=True, null=True)
    brand = models.CharField(max_length=50, blank=True)
    last4 = models.CharField(max_length=8, blank=True)
    exp_month = models.PositiveSmallIntegerField(blank=True, null=True)
    exp_year = models.PositiveSmallIntegerField(blank=True, null=True)
    mobile_money_operator = models.CharField(max_length=20, blank=True, null=True)
    phone_number = models.CharField(max_length=50, blank=True)
    account_reference = models.CharField(max_length=255, blank=True)
    provider_metadata = models.JSONField(default=dict, blank=True)
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(blank=True, null=True)
    fingerprint = models.CharField(max_length=255, blank=True, null=True)
    billing_name = models.CharField(max_length=255, blank=True)
    billing_country = models.CharField(max_length=2, blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_default", "-created_at"]

    def __str__(self):
        suffix = f" ****{self.last4}" if self.last4 else ""
        return f"{self.provider} {self.method_type}{suffix}"


class WalletTransaction(models.Model):
    TYPE_CHOICES = [
        ("DEPOSIT", "Deposit"),
        ("WITHDRAWAL", "Withdrawal"),
        ("ADJUSTMENT", "Adjustment"),
        ("TRADE_LOCK", "Trade Lock"),
        ("TRADE_RELEASE", "Trade Release"),
        ("FEE", "Fee"),
        ("REFUND", "Refund"),
    ]
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("PROCESSING", "Processing"),
        ("SUCCEEDED", "Succeeded"),
        ("FAILED", "Failed"),
        ("CANCELLED", "Cancelled"),
    ]
    PROVIDER_CHOICES = [
        ("PAYSTACK", "Paystack"),
        ("STRIPE", "Stripe"),
        ("ADYEN", "Adyen"),
        ("MANUAL", "Manual"),
    ]

    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name="transactions")
    tx_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=10, default="USD")
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, blank=True, null=True)
    provider_reference = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    provider_session_id = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    description = models.TextField(blank=True)

    KIND_CHOICES = [
        ("CASH_IN", "Cash In"),
        ("CASH_OUT", "Cash Out"),
        ("INTERNAL_TRANSFER", "Internal Transfer"),
        ("EXTERNAL_TRANSFER", "External Transfer"),
        ("CONVERSION", "Conversion"),
    ]

    kind = models.CharField(max_length=30, blank=True, null=True)
    source_provider = models.CharField(max_length=20, blank=True, null=True)
    destination_provider = models.CharField(max_length=20, blank=True, null=True)
    exchange_rate = models.DecimalField(max_digits=18, decimal_places=6, blank=True, null=True)
    gross_amount = models.DecimalField(max_digits=18, decimal_places=2, blank=True, null=True)
    net_amount = models.DecimalField(max_digits=18, decimal_places=2, blank=True, null=True)
    fee_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    external_status = models.CharField(max_length=50, blank=True)
    idempotency_key = models.CharField(max_length=255, blank=True, null=True, db_index=True)

    metadata = models.JSONField(default=dict, blank=True)
    processed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["provider", "provider_reference"]),
            models.Index(fields=["wallet", "tx_type", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_reference"],
                name="uniq_wallet_tx_provider_reference"
            )
        ]



    def __str__(self):
        return f"{self.tx_type} {self.amount} {self.currency} ({self.status})"


class WithdrawalRequest(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("UNDER_REVIEW", "Under Review"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("PAID", "Paid"),
        ("FAILED", "Failed"),
        ("CANCELLED", "Cancelled"),
    ]
    DESTINATION_CHOICES = [
        ("BANK", "Bank"),
        ("CARD", "Card"),
    ]

    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name="withdrawals")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    fee_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=10, default="USD")
    destination_type = models.CharField(max_length=20, choices=DESTINATION_CHOICES, default="BANK")
    destination_masked = models.CharField(max_length=80, blank=True, null=True)
    payment_method = models.ForeignKey(PaymentMethod, on_delete=models.SET_NULL, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    provider = models.CharField(max_length=20, blank=True, null=True)
    provider_reference = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    failure_reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_withdrawals",
    )
    admin_note = models.TextField(blank=True)

    destination = models.ForeignKey(
        "PayoutDestination",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="withdrawal_requests",
    )
    gross_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    net_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    submitted_at = models.DateTimeField(blank=True, null=True)

    paid_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Withdrawal {self.amount} {self.currency} ({self.status})"

class ProviderWebhookEvent(models.Model):
    provider = models.CharField(max_length=20)
    event_id = models.CharField(max_length=255, db_index=True)
    event_type = models.CharField(max_length=255, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    processed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        unique_together = [("provider", "event_id")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.provider}:{self.event_type}:{self.event_id}"

class WalletLedgerEntry(models.Model):
    ENTRY_TYPES = [
        ("CREDIT", "Credit"),
        ("DEBIT", "Debit"),
        ("LOCK", "Lock"),
        ("UNLOCK", "Unlock"),
        ("FEE", "Fee"),
        ("REFUND", "Refund"),
    ]

    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name="ledger_entries")
    transaction = models.ForeignKey("WalletTransaction", on_delete=models.SET_NULL, null=True, blank=True)
    entry_type = models.CharField(max_length=20, choices=ENTRY_TYPES)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    balance_before = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    balance_after = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default="USD")
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class PayoutDestination(models.Model):
    DESTINATION_TYPES = [
        ("BANK", "Bank"),
        ("CARD", "Card"),
        ("MOBILE_MONEY", "Mobile Money"),
        ("WALLET", "Wallet"),
    ]
    MOBILE_MONEY_OPERATOR_CHOICES = [
        ("ORANGE", "Orange Money"),
        ("MTN", "MTN MoMo"),
        ("WAVE", "Wave"),
        ("MOOV", "Moov Money"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payout_destinations")
    destination_type = models.CharField(max_length=20, choices=DESTINATION_TYPES)
    label = models.CharField(max_length=120)
    account_name = models.CharField(max_length=255, blank=True)
    bank_name = models.CharField(max_length=255, blank=True)
    iban = models.CharField(max_length=80, blank=True)
    phone_number = models.CharField(max_length=50, blank=True)
    provider_reference = models.CharField(max_length=255, blank=True, null=True)
    is_default = models.BooleanField(default=False)

    provider = models.CharField(max_length=20, blank=True, null=True)
    mobile_money_operator = models.CharField(max_length=20, blank=True, null=True)
    country_code = models.CharField(max_length=2, default="CI")
    currency = models.CharField(max_length=10, default="XOF")
    provider_metadata = models.JSONField(default=dict, blank=True)
    last_used_at = models.DateTimeField(blank=True, null=True)

    is_active = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_default", "-created_at"]

    def __str__(self):
        return f"{self.label} ({self.destination_type})"

class PaymentProviderAccount(models.Model):
    PROVIDER_CHOICES = [
        ("STRIPE", "Stripe"),
        ("ADYEN", "Adyen"),
        ("CINETPAY", "CinetPay"),
        ("PAYSTACK", "Paystack"),
        ("ORANGE_MONEY", "Orange Money"),
        ("MTN_MOMO", "MTN MoMo"),
        ("WAVE", "Wave"),
    ]

    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, unique=True)
    is_active = models.BooleanField(default=True)
    supports_deposit = models.BooleanField(default=True)
    supports_withdrawal = models.BooleanField(default=False)
    supported_currencies = models.JSONField(default=list, blank=True)
    supported_countries = models.JSONField(default=list, blank=True)
    credentials = models.JSONField(default=dict, blank=True)
    webhook_secret = models.CharField(max_length=255, blank=True)
    settings_json = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.provider

class WalletTransferIntent(models.Model):
    DIRECTION_CHOICES = [
        ("IN", "Inbound"),
        ("OUT", "Outbound"),
    ]
    STATUS_CHOICES = [
        ("CREATED", "Created"),
        ("INITIATED", "Initiated"),
        ("PENDING", "Pending"),
        ("SUCCEEDED", "Succeeded"),
        ("FAILED", "Failed"),
        ("CANCELLED", "Cancelled"),
        ("EXPIRED", "Expired"),
    ]

    wallet = models.ForeignKey("Wallet", on_delete=models.CASCADE, related_name="transfer_intents")
    transaction = models.ForeignKey("WalletTransaction", on_delete=models.SET_NULL, null=True, blank=True)
    provider = models.CharField(max_length=20)
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=10, default="XOF")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="CREATED")
    channel = models.CharField(max_length=30, blank=True)  # card, mobile_money, bank
    operator = models.CharField(max_length=30, blank=True) # orange, mtn, wave
    phone_number = models.CharField(max_length=50, blank=True)
    external_reference = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    checkout_url = models.URLField(blank=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    provider_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
