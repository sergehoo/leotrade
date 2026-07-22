from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.models import TimeStampedModel


class BacktestRun(TimeStampedModel):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("RUNNING", "Running"),
        ("DONE", "Done"),
        ("FAILED", "Failed"),
    ]

    strategy = models.ForeignKey(
        "strategies.Strategy",
        on_delete=models.CASCADE,
        related_name="backtests",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="backtest_runs",
    )
    name = models.CharField(max_length=150)
    start_date = models.DateField()
    end_date = models.DateField()
    initial_cash = models.DecimalField(
        max_digits=24,
        decimal_places=8,
        default=Decimal("10000"),
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    commission = models.DecimalField(
        max_digits=10,
        decimal_places=8,
        default=Decimal("0.001"),
        validators=[
            MinValueValidator(Decimal("0")),
            MaxValueValidator(Decimal("0.10")),
        ],
    )
    spread = models.DecimalField(
        max_digits=10,
        decimal_places=8,
        default=Decimal("0"),
        validators=[
            MinValueValidator(Decimal("0")),
            MaxValueValidator(Decimal("0.05")),
        ],
    )
    slippage = models.DecimalField(
        max_digits=10,
        decimal_places=8,
        default=Decimal("0"),
        validators=[
            MinValueValidator(Decimal("0")),
            MaxValueValidator(Decimal("0.05")),
        ],
    )
    parameters = models.JSONField(default=dict, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    equity_curve = models.JSONField(default=list, blank=True)
    trades_log = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="PENDING",
        db_index=True,
    )
    engine_version = models.CharField(max_length=50, default="sma-cross-v2")
    data_points = models.PositiveIntegerField(default=0)
    data_checksum = models.CharField(max_length=64, blank=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    worker_task_id = models.CharField(max_length=255, blank=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    failure_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["requested_by", "status", "created_at"]),
            models.Index(fields=["strategy", "created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["requested_by", "strategy"],
                condition=models.Q(status__in=["PENDING", "RUNNING"]),
                name="leo_bt_one_active_per_user_strategy",
            ),
            models.CheckConstraint(
                condition=models.Q(start_date__lte=models.F("end_date")),
                name="leo_bt_dates_ordered",
            ),
            models.CheckConstraint(
                condition=models.Q(initial_cash__gt=0),
                name="leo_bt_initial_cash_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(commission__gte=0, commission__lte=Decimal("0.10"))
                    & models.Q(spread__gte=0, spread__lte=Decimal("0.05"))
                    & models.Q(slippage__gte=0, slippage__lte=Decimal("0.05"))
                ),
                name="leo_bt_cost_rates_valid",
            ),
        ]

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValidationError({"end_date": "La date de fin doit suivre la date de début."})

    def __str__(self):
        return self.name
