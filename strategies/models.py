from decimal import Decimal
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from core.models import TimeStampedModel
from market.models import Asset, Timeframe


class Strategy(TimeStampedModel):
    STRATEGY_TYPE_CHOICES = [
        ("RULE", "Rule Based"),
        ("ML", "Machine Learning"),
        ("HYBRID", "Hybrid"),
    ]

    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("BACKTEST", "Backtest"),
        ("PAPER", "Paper"),
        ("LIVE", "Live"),
        ("PAUSED", "Paused"),
        ("ARCHIVED", "Archived"),
        ("FAILED", "Failed"),
    ]

    name = models.CharField(max_length=150, unique=True)
    slug = models.SlugField(unique=True, blank=True)

    strategy_type = models.CharField(
        max_length=20,
        choices=STRATEGY_TYPE_CHOICES,
        default="HYBRID",
        db_index=True,
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="DRAFT",
        db_index=True,
    )

    asset = models.ForeignKey(
        Asset,
        on_delete=models.CASCADE,
        related_name="strategies",
    )
    timeframe = models.ForeignKey(
        Timeframe,
        on_delete=models.CASCADE,
        related_name="strategies",
    )

    is_active = models.BooleanField(default=True)
    is_autonomous = models.BooleanField(default=False)
    allow_live_execution = models.BooleanField(default=False)

    run_interval_seconds = models.PositiveIntegerField(default=60)
    cooldown_seconds = models.PositiveIntegerField(default=0)
    max_signals_per_day = models.PositiveIntegerField(default=20)

    min_confidence_threshold = models.FloatField(default=0.0)
    risk_per_trade_percent = models.FloatField(default=1.0)
    max_position_size = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0"))
    max_daily_drawdown_percent = models.FloatField(default=0.0)
    max_total_exposure_percent = models.FloatField(default=100.0)

    model_path = models.CharField(max_length=500, blank=True, null=True)
    entry_rules = models.JSONField(default=dict, blank=True)
    exit_rules = models.JSONField(default=dict, blank=True)
    parameters = models.JSONField(default=dict, blank=True)
    description = models.TextField(blank=True)

    last_run_at = models.DateTimeField(blank=True, null=True)
    last_signal_at = models.DateTimeField(blank=True, null=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["status", "is_active"]),
            models.Index(fields=["asset", "timeframe"]),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            i = 1
            while Strategy.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                i += 1
                slug = f"{base_slug}-{i}"
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def is_live_mode(self):
        return self.status == "LIVE" and self.allow_live_execution

    @property
    def latest_version(self):
        return self.versions.order_by("-created_at").first()

    @property
    def latest_signal(self):
        return self.signals.order_by("-created_at").first()


class StrategyVersion(TimeStampedModel):
    strategy = models.ForeignKey(
        Strategy,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version = models.CharField(max_length=50)
    is_live = models.BooleanField(default=False)

    model_path = models.CharField(max_length=500, blank=True, null=True)
    parameters = models.JSONField(default=dict, blank=True)
    entry_rules = models.JSONField(default=dict, blank=True)
    exit_rules = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = [("strategy", "version")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.strategy.name} v{self.version}"


class StrategyRun(TimeStampedModel):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("RUNNING", "Running"),
        ("SUCCEEDED", "Succeeded"),
        ("FAILED", "Failed"),
        ("SKIPPED", "Skipped"),
    ]

    strategy = models.ForeignKey(
        Strategy,
        on_delete=models.CASCADE,
        related_name="runs",
    )
    run_started_at = models.DateTimeField(default=timezone.now)
    run_finished_at = models.DateTimeField(blank=True, null=True)
    candle_time = models.DateTimeField(blank=True, null=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="PENDING",
        db_index=True,
    )
    input_snapshot = models.JSONField(default=dict, blank=True)
    output_snapshot = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    runtime_ms = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-run_started_at"]
        indexes = [
            models.Index(fields=["strategy", "status"]),
            models.Index(fields=["strategy", "run_started_at"]),
        ]

    def __str__(self):
        return f"{self.strategy.name} - {self.status} - {self.run_started_at}"


class StrategyPrediction(TimeStampedModel):
    strategy = models.ForeignKey(
        Strategy,
        on_delete=models.CASCADE,
        related_name="predictions",
    )
    candle_time = models.DateTimeField(db_index=True)

    predicted_label = models.CharField(max_length=50, blank=True)
    predicted_score = models.FloatField(default=0.0)
    probability_up = models.FloatField(default=0.0)
    probability_down = models.FloatField(default=0.0)

    raw_output = models.JSONField(default=dict, blank=True)
    features_snapshot = models.JSONField(default=dict, blank=True)

    # Comparaison prévision/réalité — rempli a posteriori par
    # PredictionEvaluationService quand la bougie suivante est connue.
    actual_label = models.CharField(max_length=50, blank=True)
    is_correct = models.BooleanField(null=True, blank=True, db_index=True)
    evaluated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-candle_time"]
        indexes = [
            models.Index(fields=["strategy", "candle_time"]),
            models.Index(fields=["strategy", "is_correct"]),
        ]

    def __str__(self):
        return f"{self.strategy.name} - {self.candle_time}"


class Signal(TimeStampedModel):
    SIDE_CHOICES = [
        ("BUY", "Buy"),
        ("SELL", "Sell"),
        ("HOLD", "Hold"),
    ]

    STATUS_CHOICES = [
        ("NEW", "New"),
        ("SCORED", "Scored"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("QUEUED", "Queued"),
        ("EXECUTED", "Executed"),
        ("EXPIRED", "Expired"),
        ("CANCELLED", "Cancelled"),
        ("FAILED", "Failed"),
    ]

    strategy = models.ForeignKey(
        Strategy,
        on_delete=models.CASCADE,
        related_name="signals",
    )
    strategy_run = models.ForeignKey(
        StrategyRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="signals",
    )

    candle_time = models.DateTimeField(db_index=True)
    side = models.CharField(max_length=10, choices=SIDE_CHOICES, db_index=True)
    confidence = models.FloatField(default=0.0)

    price = models.DecimalField(max_digits=24, decimal_places=10)
    stop_loss = models.DecimalField(max_digits=24, decimal_places=10, blank=True, null=True)
    take_profit = models.DecimalField(max_digits=24, decimal_places=10, blank=True, null=True)

    reason = models.TextField(blank=True)
    features_snapshot = models.JSONField(default=dict, blank=True)
    model_output = models.JSONField(default=dict, blank=True)

    expires_at = models.DateTimeField(blank=True, null=True)
    approved_at = models.DateTimeField(blank=True, null=True)
    executed_at = models.DateTimeField(blank=True, null=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="NEW",
        db_index=True,
    )

    class Meta:
        ordering = ["-candle_time"]
        indexes = [
            models.Index(fields=["strategy", "status"]),
            models.Index(fields=["strategy", "candle_time"]),
            models.Index(fields=["side", "status"]),
        ]

    def __str__(self):
        return f"{self.strategy.name} - {self.side} - {self.candle_time}"

    @property
    def rr_ratio(self):
        if not self.stop_loss or not self.take_profit or not self.price:
            return 0.0

        entry = float(self.price)
        sl = float(self.stop_loss)
        tp = float(self.take_profit)

        if self.side == "BUY":
            risk = entry - sl
            reward = tp - entry
        elif self.side == "SELL":
            risk = sl - entry
            reward = entry - tp
        else:
            return 0.0

        if risk <= 0:
            return 0.0
        return reward / risk


class StrategyPerformanceSnapshot(TimeStampedModel):
    strategy = models.ForeignKey(
        Strategy,
        on_delete=models.CASCADE,
        related_name="performance_snapshots",
    )
    snapshot_time = models.DateTimeField(default=timezone.now, db_index=True)

    signals_count = models.PositiveIntegerField(default=0)
    executed_signals_count = models.PositiveIntegerField(default=0)
    win_rate = models.FloatField(default=0.0)
    avg_return = models.FloatField(default=0.0)
    sharpe_ratio = models.FloatField(default=0.0)
    max_drawdown = models.FloatField(default=0.0)

    class Meta:
        ordering = ["-snapshot_time"]
        indexes = [
            models.Index(fields=["strategy", "snapshot_time"]),
        ]

    def __str__(self):
        return f"{self.strategy.name} @ {self.snapshot_time}"