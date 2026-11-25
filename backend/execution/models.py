from django.db import models
from django.db.models import Q
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
        ("SUBMITTING", "Submitting"),
        ("UNKNOWN_BROKER_STATE", "Unknown Broker State"),
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
    closes_position = models.ForeignKey(
        "portfolio.Position",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="closing_orders",
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
    strategy_deployment = models.ForeignKey(
        "strategies.StrategyDeployment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="orders",
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
    # ⚠ UNITÉ NON GARANTIE — défaut connu, à résorber.
    #
    # Trois producteurs écrivent des grandeurs de natures différentes dans ce
    # même champ :
    #   1. risk/services.py, PositionSizingService.compute → quantité en
    #      unités de sous-jacent (montant / prix). C'est l'intention.
    #   2. risk/services.py:1010, branche Deriv → `requested_stake`, soit un
    #      MONTANT EN DEVISE.
    #   3. market/views.py:644, Quick Trade hors Deriv → `amount`, soit un
    #      MONTANT EN DEVISE (le commentaire sur place l'assume : « en quick
    #      trade on utilise stake = qty »).
    #
    # Conséquence : aucun consommateur ne peut convertir ce champ sans savoir
    # par quel chemin il a été écrit. C'est pourquoi la garde d'unité MT5
    # (infrastructure/broker_clients/mt5_client.py, submit_order) REFUSE
    # d'ouvrir plutôt que de convertir quand 1 lot ≠ 1 unité.
    #
    # Résorber le défaut suppose de donner une unité unique à ce champ et de
    # reprendre les 9 appelants de ExecutionOrchestrator.create_order ; ce
    # n'est pas un correctif ponctuel.
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
        constraints = [
            models.UniqueConstraint(
                fields=["closes_position"],
                condition=(
                    Q(closes_position__isnull=False)
                    & Q(status__in=[
                        "PENDING_SUBMIT",
                        "SUBMITTING",
                        "UNKNOWN_BROKER_STATE",
                        "SUBMITTED",
                        "PARTIALLY_FILLED",
                    ])
                ),
                name="uniq_active_close_order_position",
            ),
        ]

    def __str__(self):
        return f"{self.symbol} {self.side} {self.approved_quantity} [{self.status}]"

    @property
    def remaining_quantity(self):
        return max(Decimal("0"), self.approved_quantity - self.filled_quantity)

    @property
    def is_open(self):
        return self.status in {
            "PENDING_SUBMIT",
            "SUBMITTING",
            "UNKNOWN_BROKER_STATE",
            "SUBMITTED",
            "PARTIALLY_FILLED",
        }


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
        constraints = [
            models.UniqueConstraint(
                fields=["order", "broker_fill_id"],
                condition=Q(broker_fill_id__isnull=False) & ~Q(broker_fill_id=""),
                name="uniq_order_broker_fill_id",
            ),
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
        ("ORDER_STATE_UNKNOWN", "Order State Unknown"),
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


class PositionProtection(TimeStampedModel):
    MODE_CHOICES = [
        ("LOCAL_MONITORED", "Local monitored"),
        ("NATIVE_BROKER", "Native broker"),
        ("UNSUPPORTED", "Unsupported"),
    ]

    STATUS_CHOICES = [
        ("ACTIVE", "Active"),
        ("EXECUTING", "Executing"),
        ("COMPLETED", "Completed"),
        ("FAILED", "Failed"),
        ("DISABLED", "Disabled"),
    ]

    position = models.OneToOneField(
        "portfolio.Position",
        on_delete=models.CASCADE,
        related_name="protection",
    )
    close_order = models.OneToOneField(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="position_protection",
    )
    mode = models.CharField(max_length=30, choices=MODE_CHOICES, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="ACTIVE",
        db_index=True,
    )

    stop_loss = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    take_profit = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    trailing_enabled = models.BooleanField(default=False)
    trail_percent = models.DecimalField(
        max_digits=8,
        decimal_places=6,
        default=Decimal("0.015000"),
    )
    atr = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    atr_multiplier = models.DecimalField(
        max_digits=8,
        decimal_places=4,
        default=Decimal("2.0000"),
    )
    break_even_after_r = models.DecimalField(
        max_digits=8,
        decimal_places=4,
        default=Decimal("1.0000"),
    )

    high_watermark = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    low_watermark = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    last_price = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    last_evaluated_at = models.DateTimeField(null=True, blank=True, db_index=True)
    triggered_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    trigger_reason = models.CharField(max_length=40, blank=True)
    last_error = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["mode", "status"]),
            models.Index(fields=["status", "last_evaluated_at"]),
        ]

    def __str__(self):
        return f"Protection position {self.position_id} [{self.mode}/{self.status}]"


from .models_idempotency import IdempotencyKey
