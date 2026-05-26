from __future__ import annotations

from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Portfolio(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="portfolios",
    )
    broker_account = models.ForeignKey(
        "brokers.BrokerAccount",
        on_delete=models.CASCADE,
        related_name="portfolios",
    )

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, null=True)
    base_currency = models.CharField(max_length=10, default="USD", db_index=True)

    starting_balance = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    current_balance = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    available_cash = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    locked_cash = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    equity = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    unrealized_pnl = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    realized_pnl = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    margin_used = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    max_equity = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    current_drawdown_percent = models.FloatField(default=0.0)
    max_drawdown_percent = models.FloatField(default=0.0)

    is_active = models.BooleanField(default=True, db_index=True)
    is_default = models.BooleanField(default=False, db_index=True)

    last_reconciled_at = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("user", "name")]
        indexes = [
            models.Index(fields=["user", "is_default"]),
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["broker_account", "is_active"]),
        ]

    def __str__(self):
        return f"{self.user} - {self.name}"

    def clean(self):
        errors = {}

        if self.broker_account and self.user_id and self.broker_account.user_id != self.user_id:
            errors["broker_account"] = "Le broker account doit appartenir au même utilisateur."

        if self.is_default:
            qs = Portfolio.objects.filter(user=self.user, is_default=True)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                errors["is_default"] = "Un seul portefeuille par défaut est autorisé par utilisateur."

        if self.starting_balance < 0:
            errors["starting_balance"] = "Le solde initial ne peut pas être négatif."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.pk and self.current_balance == Decimal("0.00"):
            self.current_balance = self.starting_balance
        if not self.pk and self.available_cash == Decimal("0.00"):
            self.available_cash = self.current_balance
        if not self.pk and self.equity == Decimal("0.00"):
            self.equity = self.current_balance
        if not self.pk and self.max_equity == Decimal("0.00"):
            self.max_equity = self.equity

        self.full_clean()
        super().save(*args, **kwargs)


class CashLedgerEntry(TimeStampedModel):
    ENTRY_TYPE_CHOICES = [
        ("DEPOSIT", "Deposit"),
        ("WITHDRAWAL", "Withdrawal"),
        ("ORDER_LOCK", "Order Lock"),
        ("ORDER_RELEASE", "Order Release"),
        ("FEE", "Fee"),
        ("PNL_REALIZED", "Realized PnL"),
        ("TRADE_EXECUTION", "Trade Execution"),
        ("BROKER_IMPORT", "Broker Import"),
        ("MANUAL_ADJUSTMENT", "Manual Adjustment"),
    ]

    portfolio = models.ForeignKey(
        Portfolio,
        on_delete=models.CASCADE,
        related_name="ledger_entries",
    )
    entry_type = models.CharField(max_length=30, choices=ENTRY_TYPE_CHOICES, db_index=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=10, default="USD")
    reference_type = models.CharField(max_length=50, blank=True, null=True)
    reference_id = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["portfolio", "entry_type"]),
            models.Index(fields=["portfolio", "created_at"]),
            models.Index(fields=["reference_type", "reference_id"]),
        ]

    def __str__(self):
        return f"{self.portfolio.name} - {self.entry_type} - {self.amount}"


class Position(TimeStampedModel):
    SIDE_CHOICES = [
        ("LONG", "Long"),
        ("SHORT", "Short"),
    ]

    STATUS_CHOICES = [
        ("OPEN", "Open"),
        ("PARTIALLY_CLOSED", "Partially Closed"),
        ("CLOSED", "Closed"),
    ]

    SOURCE_CHOICES = [
        ("MANUAL", "Manual"),
        ("IMPORTED", "Imported"),
        ("STRATEGY", "Strategy"),
        ("AI_ASSISTED", "AI Assisted"),
    ]

    COST_BASIS_STATUS_CHOICES = [
        ("KNOWN", "Known"),
        ("ESTIMATED", "Estimated"),
        ("UNKNOWN", "Unknown"),
    ]

    portfolio = models.ForeignKey(
        Portfolio,
        on_delete=models.CASCADE,
        related_name="positions",
    )
    broker_account = models.ForeignKey(
        "brokers.BrokerAccount",
        on_delete=models.CASCADE,
        related_name="positions",
    )
    asset = models.ForeignKey(
        "market.Asset",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="positions",
    )

    symbol = models.CharField(max_length=50, db_index=True)
    asset_name = models.CharField(max_length=150, blank=True, null=True)

    side = models.CharField(max_length=10, choices=SIDE_CHOICES, default="LONG", db_index=True)
    quantity = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0"))
    entry_price = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0"))
    average_entry_price = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0"))
    current_price = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0"))

    stop_loss = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    take_profit = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)

    leverage = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("1"))
    margin_used = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    notional_value = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    exposure_value = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="OPEN", db_index=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="MANUAL", db_index=True)
    cost_basis_status = models.CharField(
        max_length=20,
        choices=COST_BASIS_STATUS_CHOICES,
        default="KNOWN",
        db_index=True,
    )

    pnl = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    pnl_percent = models.FloatField(default=0.0)
    realized_pnl = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    unrealized_pnl = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    broker_position_id = models.CharField(max_length=120, blank=True, null=True, db_index=True)
    broker_order_id = models.CharField(max_length=120, blank=True, null=True, db_index=True)

    opened_at = models.DateTimeField(default=timezone.now, db_index=True)
    closed_at = models.DateTimeField(blank=True, null=True, db_index=True)

    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-opened_at"]
        indexes = [
            models.Index(fields=["portfolio", "status"]),
            models.Index(fields=["portfolio", "symbol"]),
            models.Index(fields=["broker_account", "status"]),
            models.Index(fields=["broker_position_id"]),
        ]

    def __str__(self):
        return f"{self.portfolio.name} - {self.symbol} - {self.side}"

    def clean(self):
        errors = {}

        if self.portfolio_id and self.broker_account_id:
            if self.portfolio.broker_account_id != self.broker_account_id:
                errors["broker_account"] = "Le broker de la position doit correspondre à celui du portefeuille."

        if self.quantity <= 0:
            errors["quantity"] = "La quantité doit être strictement positive."

        if self.entry_price < 0:
            errors["entry_price"] = "Le prix d'entrée ne peut pas être négatif."

        if self.current_price < 0:
            errors["current_price"] = "Le prix courant ne peut pas être négatif."

        if self.status == "CLOSED" and not self.closed_at:
            self.closed_at = timezone.now()

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.average_entry_price:
            self.average_entry_price = self.entry_price
        self.full_clean()
        super().save(*args, **kwargs)

    def update_market_metrics(self):
        price = self.current_price or self.entry_price or Decimal("0")
        quantity = self.quantity or Decimal("0")
        entry = self.average_entry_price or self.entry_price or Decimal("0")

        if quantity <= 0 or price <= 0 or entry <= 0:
            self.notional_value = Decimal("0.00")
            self.exposure_value = Decimal("0.00")
            self.unrealized_pnl = Decimal("0.00")
            self.pnl = Decimal("0.00")
            self.pnl_percent = 0.0
            return

        self.notional_value = (quantity * price).quantize(Decimal("0.01"))
        self.exposure_value = self.notional_value

        if self.side == "LONG":
            diff = price - entry
        else:
            diff = entry - price

        unrealized = (diff * quantity).quantize(Decimal("0.01"))
        self.unrealized_pnl = unrealized
        self.pnl = (self.realized_pnl + self.unrealized_pnl).quantize(Decimal("0.01"))

        base_cost = (entry * quantity)
        if base_cost > 0:
            self.pnl_percent = float((self.unrealized_pnl / base_cost) * Decimal("100"))
        else:
            self.pnl_percent = 0.0


class PortfolioSnapshot(TimeStampedModel):
    portfolio = models.ForeignKey(
        Portfolio,
        on_delete=models.CASCADE,
        related_name="snapshots",
    )
    snapshot_time = models.DateTimeField(default=timezone.now, db_index=True)
    balance = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    available_cash = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    locked_cash = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    equity = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    unrealized_pnl = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    realized_pnl = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    margin_used = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    drawdown_percent = models.FloatField(default=0.0)
    daily_return_percent = models.FloatField(default=0.0)
    monthly_return_percent = models.FloatField(default=0.0)

    class Meta:
        ordering = ["-snapshot_time"]
        indexes = [
            models.Index(fields=["portfolio", "snapshot_time"]),
        ]


class PortfolioAllocation(TimeStampedModel):
    portfolio = models.ForeignKey(
        Portfolio,
        on_delete=models.CASCADE,
        related_name="allocations",
    )
    asset = models.ForeignKey(
        "market.Asset",
        on_delete=models.CASCADE,
        related_name="portfolio_allocations",
    )
    target_weight = models.FloatField(default=0.0)
    max_weight = models.FloatField(default=100.0)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("portfolio", "asset")]
        ordering = ["asset__symbol"]


class PositionCorrelation(TimeStampedModel):
    portfolio = models.ForeignKey(
        Portfolio,
        on_delete=models.CASCADE,
        related_name="position_correlations",
    )
    asset_a = models.ForeignKey(
        "market.Asset",
        on_delete=models.CASCADE,
        related_name="correlation_asset_a",
    )
    asset_b = models.ForeignKey(
        "market.Asset",
        on_delete=models.CASCADE,
        related_name="correlation_asset_b",
    )
    timeframe_code = models.CharField(max_length=20, default="1d")
    lookback_bars = models.PositiveIntegerField(default=90)
    correlation_value = models.FloatField(default=0.0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["portfolio", "timeframe_code"]),
        ]


# Phase 3 — Trade (round-trip clos). Source de vérité unique pour realized_pnl.
# Cet import doit rester en bas du fichier pour que Django découvre le modèle
# défini dans portfolio/models_trade.py au moment du chargement de l'app.
from portfolio.models_trade import Trade  # noqa: E402,F401


# # /Users/ogahserge/Documents/leoTrade/portfolio/models.py
#
# from __future__ import annotations
#
# from decimal import Decimal, InvalidOperation
#
# from django.contrib.auth import get_user_model
# from django.core.exceptions import ValidationError
# from django.db import models
# from django.utils import timezone
#
# from core.models import TimeStampedModel
# from market.models import Asset
#
# User = get_user_model()
#
#
# DECIMAL_ZERO = Decimal("0")
# MONEY_DECIMALS = Decimal("0.00000001")
# PRICE_DECIMALS = Decimal("0.0000000001")
#
#
# def _to_decimal(value, default="0") -> Decimal:
#     try:
#         if value is None or value == "":
#             return Decimal(default)
#         return Decimal(str(value))
#     except (InvalidOperation, TypeError, ValueError):
#         return Decimal(default)
#
#
# def _quantize_money(value: Decimal) -> Decimal:
#     value = _to_decimal(value, "0")
#     return value.quantize(MONEY_DECIMALS)
#
#
# def _quantize_price(value: Decimal) -> Decimal:
#     value = _to_decimal(value, "0")
#     return value.quantize(PRICE_DECIMALS)
#
#
# class Portfolio(TimeStampedModel):
#     from brokers.models import BrokerAccount
#
#     user = models.ForeignKey(
#         User,
#         on_delete=models.CASCADE,
#         related_name="portfolios",
#     )
#     broker_account = models.ForeignKey(
#         BrokerAccount,
#         on_delete=models.CASCADE,
#         related_name="portfolios",
#     )
#
#     name = models.CharField(max_length=150)
#     description = models.TextField(blank=True)
#
#     base_currency = models.CharField(max_length=10, default="USDT")
#
#     # Solde initial du portefeuille
#     starting_balance = models.DecimalField(
#         max_digits=32,
#         decimal_places=8,
#         default=Decimal("10000"),
#     )
#
#     # Cash disponible / non engagé
#     current_balance = models.DecimalField(
#         max_digits=32,
#         decimal_places=8,
#         default=Decimal("10000"),
#     )
#
#     # Cash + PnL latent
#     equity = models.DecimalField(
#         max_digits=32,
#         decimal_places=8,
#         default=Decimal("10000"),
#     )
#
#     max_equity = models.DecimalField(
#         max_digits=32,
#         decimal_places=8,
#         default=Decimal("10000"),
#     )
#
#     current_drawdown_percent = models.FloatField(default=0.0)
#     max_drawdown_percent = models.FloatField(default=0.0)
#
#     is_active = models.BooleanField(default=True)
#     is_default = models.BooleanField(default=False)
#
#     class Meta:
#         ordering = ["name"]
#         unique_together = [("user", "name")]
#         indexes = [
#             models.Index(fields=["user", "is_default"]),
#             models.Index(fields=["user", "is_active"]),
#         ]
#
#     def __str__(self):
#         return self.name
#
#     def clean(self):
#         if self.is_default:
#             qs = Portfolio.objects.filter(user=self.user, is_default=True)
#             if self.pk:
#                 qs = qs.exclude(pk=self.pk)
#             if qs.exists():
#                 raise ValidationError({
#                     "is_default": "Un seul portfolio par utilisateur peut être défini par défaut."
#                 })
#
#         if self.current_balance is not None and _to_decimal(self.current_balance) < 0:
#             raise ValidationError({
#                 "current_balance": "Le solde disponible ne peut pas être négatif."
#             })
#
#         if self.starting_balance is not None and _to_decimal(self.starting_balance) < 0:
#             raise ValidationError({
#                 "starting_balance": "Le solde initial ne peut pas être négatif."
#             })
#
#     def save(self, *args, **kwargs):
#         self.starting_balance = _quantize_money(self.starting_balance)
#         self.current_balance = _quantize_money(self.current_balance)
#         self.equity = _quantize_money(self.equity)
#         self.max_equity = _quantize_money(self.max_equity)
#         self.full_clean()
#         super().save(*args, **kwargs)
#
#     @property
#     def open_positions_queryset(self):
#         return self.positions.filter(status="OPEN").select_related("asset")
#
#     @property
#     def closed_positions_queryset(self):
#         return self.positions.filter(status="CLOSED").select_related("asset")
#
#     @property
#     def unrealized_pnl(self) -> Decimal:
#         total = DECIMAL_ZERO
#         for p in self.open_positions_queryset:
#             total += _to_decimal(p.pnl, "0")
#         return _quantize_money(total)
#
#     @property
#     def realized_pnl(self) -> Decimal:
#         total = DECIMAL_ZERO
#         for p in self.closed_positions_queryset:
#             total += _to_decimal(p.pnl, "0")
#         return _quantize_money(total)
#
#     @property
#     def total_positions_open(self) -> int:
#         return self.positions.filter(status="OPEN").count()
#
#     @property
#     def gross_exposure(self) -> Decimal:
#         total = DECIMAL_ZERO
#         for p in self.open_positions_queryset:
#             total += _to_decimal(p.exposure_value, "0")
#         return _quantize_money(total)
#
#
# class Position(TimeStampedModel):
#     SIDE_CHOICES = [
#         ("LONG", "Long"),
#         ("SHORT", "Short"),
#     ]
#
#     STATUS_CHOICES = [
#         ("OPEN", "Open"),
#         ("CLOSED", "Closed"),
#     ]
#
#     portfolio = models.ForeignKey(
#         Portfolio,
#         on_delete=models.CASCADE,
#         related_name="positions",
#     )
#     asset = models.ForeignKey(
#         Asset,
#         on_delete=models.CASCADE,
#         related_name="positions",
#     )
#
#     side = models.CharField(max_length=10, choices=SIDE_CHOICES)
#     quantity = models.DecimalField(max_digits=32, decimal_places=10)
#     entry_price = models.DecimalField(max_digits=32, decimal_places=10)
#
#     # Prix live injecté par les services de marché / exécution
#     current_price = models.DecimalField(
#         max_digits=32,
#         decimal_places=10,
#         blank=True,
#         null=True,
#     )
#
#     stop_loss = models.DecimalField(
#         max_digits=32,
#         decimal_places=10,
#         blank=True,
#         null=True,
#     )
#     take_profit = models.DecimalField(
#         max_digits=32,
#         decimal_places=10,
#         blank=True,
#         null=True,
#     )
#
#     status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="OPEN")
#     opened_at = models.DateTimeField(default=timezone.now)
#     closed_at = models.DateTimeField(blank=True, null=True)
#
#     pnl = models.DecimalField(
#         max_digits=32,
#         decimal_places=8,
#         default=Decimal("0"),
#     )
#     pnl_percent = models.FloatField(default=0.0)
#     exposure_value = models.DecimalField(
#         max_digits=32,
#         decimal_places=8,
#         default=Decimal("0"),
#     )
#
#     class Meta:
#         ordering = ["-opened_at"]
#         indexes = [
#             models.Index(fields=["portfolio", "status"]),
#             models.Index(fields=["asset", "status"]),
#             models.Index(fields=["portfolio", "asset"]),
#         ]
#
#     def __str__(self):
#         symbol = getattr(self.asset, "symbol", "ASSET")
#         return f"{symbol} {self.side} {self.status}"
#
#     def clean(self):
#         errors = {}
#
#         if self.side not in dict(self.SIDE_CHOICES):
#             errors["side"] = "Direction invalide."
#
#         if self.status not in dict(self.STATUS_CHOICES):
#             errors["status"] = "Statut invalide."
#
#         if _to_decimal(self.quantity, "0") <= 0:
#             errors["quantity"] = "La quantité doit être supérieure à zéro."
#
#         if _to_decimal(self.entry_price, "0") < 0:
#             errors["entry_price"] = "Le prix d'entrée ne peut pas être négatif."
#
#         if self.current_price is not None and _to_decimal(self.current_price, "0") < 0:
#             errors["current_price"] = "Le prix courant ne peut pas être négatif."
#
#         if self.stop_loss is not None and _to_decimal(self.stop_loss, "0") < 0:
#             errors["stop_loss"] = "Le stop loss ne peut pas être négatif."
#
#         if self.take_profit is not None and _to_decimal(self.take_profit, "0") < 0:
#             errors["take_profit"] = "Le take profit ne peut pas être négatif."
#
#         if self.status == "CLOSED" and not self.closed_at:
#             errors["closed_at"] = "Une position clôturée doit avoir une date de clôture."
#
#         if self.status == "OPEN" and self.closed_at:
#             errors["closed_at"] = "Une position ouverte ne peut pas avoir de date de clôture."
#
#         if errors:
#             raise ValidationError(errors)
#
#     def save(self, *args, **kwargs):
#         self.quantity = _quantize_price(self.quantity)
#         self.entry_price = _quantize_price(self.entry_price)
#
#         if self.current_price is not None:
#             self.current_price = _quantize_price(self.current_price)
#
#         if self.stop_loss is not None:
#             self.stop_loss = _quantize_price(self.stop_loss)
#
#         if self.take_profit is not None:
#             self.take_profit = _quantize_price(self.take_profit)
#
#         self.pnl = _quantize_money(self.pnl)
#         self.exposure_value = _quantize_money(self.exposure_value)
#
#         self.full_clean()
#         super().save(*args, **kwargs)
#
#     @property
#     def effective_price(self) -> Decimal:
#         """
#         Prix utilisé pour les calculs :
#         - current_price si disponible et > 0
#         - sinon entry_price
#         """
#         current_price = _to_decimal(self.current_price, "0")
#         if current_price > 0:
#             return current_price
#         return _to_decimal(self.entry_price, "0")
#
#     @property
#     def is_open(self) -> bool:
#         return self.status == "OPEN"
#
#     @property
#     def is_closed(self) -> bool:
#         return self.status == "CLOSED"
#
#     def close(self, close_price: Decimal | None = None, when=None):
#         if close_price is not None:
#             self.current_price = _quantize_price(close_price)
#
#         self.update_market_metrics()
#         self.status = "CLOSED"
#         self.closed_at = when or timezone.now()
#
#     def update_market_metrics(self):
#         """
#         Recalcule :
#         - pnl
#         - pnl_percent
#         - exposure_value
#
#         Hypothèse :
#         le service live ou l'exécuteur a déjà injecté current_price.
#         """
#         entry_price = _to_decimal(self.entry_price, "0")
#         current_price = self.effective_price
#         quantity = _to_decimal(self.quantity, "0")
#
#         if entry_price <= 0 or quantity <= 0:
#             self.pnl = _quantize_money(DECIMAL_ZERO)
#             self.pnl_percent = 0.0
#             self.exposure_value = _quantize_money(DECIMAL_ZERO)
#             return
#
#         if self.side == "LONG":
#             pnl_value = (current_price - entry_price) * quantity
#             pct = ((current_price - entry_price) / entry_price) * Decimal("100")
#         else:
#             pnl_value = (entry_price - current_price) * quantity
#             pct = ((entry_price - current_price) / entry_price) * Decimal("100")
#
#         exposure_reference_price = current_price if current_price > 0 else entry_price
#         exposure_value = exposure_reference_price * quantity
#
#         self.pnl = _quantize_money(pnl_value)
#         self.pnl_percent = float(pct)
#         self.exposure_value = _quantize_money(exposure_value)
#
#
# class PortfolioSnapshot(TimeStampedModel):
#     portfolio = models.ForeignKey(
#         Portfolio,
#         on_delete=models.CASCADE,
#         related_name="snapshots",
#     )
#     snapshot_time = models.DateTimeField(default=timezone.now, db_index=True)
#
#     balance = models.DecimalField(max_digits=32, decimal_places=8, default=Decimal("0"))
#     equity = models.DecimalField(max_digits=32, decimal_places=8, default=Decimal("0"))
#     unrealized_pnl = models.DecimalField(max_digits=32, decimal_places=8, default=Decimal("0"))
#     realized_pnl = models.DecimalField(max_digits=32, decimal_places=8, default=Decimal("0"))
#
#     drawdown_percent = models.FloatField(default=0.0)
#     daily_return_percent = models.FloatField(default=0.0)
#     monthly_return_percent = models.FloatField(default=0.0)
#
#     class Meta:
#         ordering = ["-snapshot_time"]
#         indexes = [
#             models.Index(fields=["portfolio", "snapshot_time"]),
#         ]
#
#     def __str__(self):
#         return f"{self.portfolio.name} @ {self.snapshot_time}"
#
#
# class PortfolioAllocation(TimeStampedModel):
#     portfolio = models.ForeignKey(
#         Portfolio,
#         on_delete=models.CASCADE,
#         related_name="allocations",
#     )
#     asset = models.ForeignKey(
#         Asset,
#         on_delete=models.CASCADE,
#         related_name="portfolio_allocations",
#     )
#
#     target_weight = models.FloatField(default=0.0)
#     max_weight = models.FloatField(default=100.0)
#     is_active = models.BooleanField(default=True)
#
#     class Meta:
#         unique_together = [("portfolio", "asset")]
#         ordering = ["asset__symbol"]
#
#     def __str__(self):
#         return f"{self.portfolio.name} - {self.asset.symbol}"
#
#
# class PositionCorrelation(TimeStampedModel):
#     portfolio = models.ForeignKey(
#         Portfolio,
#         on_delete=models.CASCADE,
#         related_name="correlations",
#     )
#     asset_a = models.ForeignKey(
#         Asset,
#         on_delete=models.CASCADE,
#         related_name="corr_asset_a",
#     )
#     asset_b = models.ForeignKey(
#         Asset,
#         on_delete=models.CASCADE,
#         related_name="corr_asset_b",
#     )
#
#     timeframe_code = models.CharField(max_length=10, default="1d")
#     lookback_bars = models.PositiveIntegerField(default=90)
#     correlation_value = models.FloatField(default=0.0)
#
#     class Meta:
#         unique_together = [
#             ("portfolio", "asset_a", "asset_b", "timeframe_code", "lookback_bars")
#         ]
#
#     def __str__(self):
#         return f"{self.asset_a.symbol}/{self.asset_b.symbol} = {self.correlation_value}"