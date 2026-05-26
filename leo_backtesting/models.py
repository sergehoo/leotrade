from django.db import models

# Create your models here.
from django.db import models
from core.models import TimeStampedModel
from strategies.models import Strategy

class BacktestRun(TimeStampedModel):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("RUNNING", "Running"),
        ("DONE", "Done"),
        ("FAILED", "Failed"),
    ]

    strategy = models.ForeignKey('strategies.Strategy', on_delete=models.CASCADE, related_name="backtests")
    name = models.CharField(max_length=150)
    start_date = models.DateField()
    end_date = models.DateField()
    initial_cash = models.DecimalField(max_digits=24, decimal_places=8, default=10000)
    commission = models.FloatField(default=0.001)
    slippage = models.FloatField(default=0.0)
    parameters = models.JSONField(default=dict, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    equity_curve = models.JSONField(default=list, blank=True)
    trades_log = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")

    def __str__(self):
        return self.name