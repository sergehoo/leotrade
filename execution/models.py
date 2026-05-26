from django.db import models
from decimal import Decimal
from django.conf import settings
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Order(TimeStampedModel):
    SIDE_CHOICES = [
        ("BUY", "Buy"),
        ("SELL", "Sell"),
    ]

    ORDER_TYPE_CHOICES = [
        ("MARKET", "Market"),
        ("LIMIT", "Limit"),
        ("STOP", "Stop"),
        ("STOP_LIMIT", "Stop Limit"),
    ]

    STATUS_CHOICES = [
        ("PENDING_APPROVAL", "Pending Approval"),
        ("PENDING_SUBMIT", "Pending Submit"),
        ("SUBMITTED", "Submitted"),
        ("PARTIALLY_FILLED", "Partially Filled"),
        ("FILLED", "Filled"),
        ("CANCELLED", "Cancelled"),
        ("REJECTED", "Rejected"),
        ("EXPIRED", "Expired"),
        ("FAILED", "Failed"),
    ]

    MODE_CHOICES = [
        ("PAPER", "Paper"),
        ("LIVE", "Live"),
    ]

    SOURCE_CHOICES = [
        ("MANUAL", "Manual"),
        ("AI_ASSISTED", "AI Assisted"),
        ("STRATEGY", "Strategy"),
        ("IMPORT", "Import"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="execution_orders",
    )
    portfolio = models.ForeignKey(
        "portfolio.Portfolio",
        on_delete=models.CASCADE,
        related_name="execution_orders",
    )
    broker_account = models.ForeignKey(
        "brokers.BrokerAccount",
        on_delete=models.CASCADE,
        related_name="execution_orders",
    )
    signal = models.ForeignKey(
        "strategies.Signal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="execution_orders",
    )
    trade_idea = models.ForeignKey(
        "trading.TradeIdea",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="execution_orders",
    )
    asset = models.ForeignKey(
        "market.Asset",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="execution_orders",
    )

    symbol = models.CharField(max_length=50, db_index=True)
    asset_name = models.CharField(max_length=150, blank=True, null=True)

    side = models.CharField(max_length=10, choices=SIDE_CHOICES, db_index=True)
    order_type = models.CharField(max_length=20, choices=ORDER_TYPE_CHOICES, default="MARKET")
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default="PAPER", db_index=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="MANUAL", db_index=True)

    requested_quantity = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0"))
    approved_quantity = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0"))
    filled_quantity = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0"))

    requested_stake_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    approved_notional = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    filled_notional = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    requested_price = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0"))
    limit_price = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    stop_price = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    average_fill_price = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0"))

    stop_loss = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    take_profit = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)

    leverage = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("1"))
    estimated_fee = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    actual_fee = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="PENDING_SUBMIT", db_index=True)
    broker_order_id = models.CharField(max_length=120, blank=True, null=True, db_index=True)
    broker_client_order_id = models.CharField(max_length=120, blank=True, null=True, db_index=True)

    submitted_at = models.DateTimeField(blank=True, null=True, db_index=True)
    filled_at = models.DateTimeField(blank=True, null=True, db_index=True)
    cancelled_at = models.DateTimeField(blank=True, null=True, db_index=True)
    rejected_at = models.DateTimeField(blank=True, null=True, db_index=True)
    expired_at = models.DateTimeField(blank=True, null=True, db_index=True)

    idempotency_key = models.CharField(max_length=120, unique=True, db_index=True)
    execution_notes = models.TextField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["portfolio", "status"]),
            models.Index(fields=["broker_account", "status"]),
            models.Index(fields=["symbol", "status"]),
            models.Index(fields=["mode", "status"]),
        ]

    def __str__(self):
        return f"{self.symbol} {self.side} {self.approved_quantity} [{self.status}]"

    @property
    def remaining_quantity(self):
        return max(Decimal("0"), self.approved_quantity - self.filled_quantity)

    @property
    def is_open(self):
        return self.status in {"PENDING_SUBMIT", "SUBMITTED", "PARTIALLY_FILLED"}


class ExecutionFill(TimeStampedModel):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="fills",
    )
    broker_fill_id = models.CharField(max_length=120, blank=True, null=True, db_index=True)
    quantity = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0"))
    price = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0"))
    notional = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    fee = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    fee_currency = models.CharField(max_length=10, default="USD")
    fill_time = models.DateTimeField(default=timezone.now, db_index=True)
    liquidity_type = models.CharField(max_length=20, blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["fill_time", "id"]
        indexes = [
            models.Index(fields=["order", "fill_time"]),
            models.Index(fields=["broker_fill_id"]),
        ]

    def __str__(self):
        return f"Fill {self.order_id} - {self.quantity}@{self.price}"


class ExecutionEvent(TimeStampedModel):
    EVENT_TYPE_CHOICES = [
        ("ORDER_CREATED", "Order Created"),
        ("ORDER_VALIDATED", "Order Validated"),
        ("ORDER_SUBMITTED", "Order Submitted"),
        ("ORDER_ACKNOWLEDGED", "Order Acknowledged"),
        ("ORDER_PARTIALLY_FILLED", "Order Partially Filled"),
        ("ORDER_FILLED", "Order Filled"),
        ("ORDER_CANCELLED", "Order Cancelled"),
        ("ORDER_REJECTED", "Order Rejected"),
        ("ORDER_FAILED", "Order Failed"),
        ("RECONCILIATION_UPDATE", "Reconciliation Update"),
    ]

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="events",
    )
    event_type = models.CharField(max_length=30, choices=EVENT_TYPE_CHOICES, db_index=True)
    message = models.TextField(blank=True, null=True)
    payload = models.JSONField(default=dict, blank=True)
    created_by_system = models.BooleanField(default=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["order", "event_type"]),
        ]

    def __str__(self):
        return f"{self.order_id} - {self.event_type}"


class BrokerSyncLog(TimeStampedModel):
    SYNC_TYPE_CHOICES = [
        ("ORDERS", "Orders"),
        ("POSITIONS", "Positions"),
        ("BALANCE", "Balance"),
        ("FULL", "Full"),
    ]

    STATUS_CHOICES = [
        ("STARTED", "Started"),
        ("SUCCESS", "Success"),
        ("PARTIAL", "Partial"),
        ("FAILED", "Failed"),
    ]

    broker_account = models.ForeignKey(
        "brokers.BrokerAccount",
        on_delete=models.CASCADE,
        related_name="sync_logs",
    )
    portfolio = models.ForeignKey(
        "portfolio.Portfolio",
        on_delete=models.CASCADE,
        related_name="broker_sync_logs",
    )
    sync_type = models.CharField(max_length=20, choices=SYNC_TYPE_CHOICES, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="STARTED", db_index=True)
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    processed_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    message = models.TextField(blank=True, null=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at"]


from .models_idempotency import IdempotencyKey