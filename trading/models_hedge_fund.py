from __future__ import annotations

from decimal import Decimal
from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import TimeStampedModel
from market.models import Asset, Timeframe
from portfolio.models import Portfolio
from strategies.models import Strategy, Signal
from trading.models import TradeIdea


class MarketRegimeState(TimeStampedModel):
    REGIME_CHOICES = [
        ("BULL_TREND", "Bull Trend"),
        ("BEAR_TREND", "Bear Trend"),
        ("SIDEWAYS", "Sideways"),
        ("HIGH_VOLATILITY", "High Volatility"),
        ("RISK_OFF", "Risk Off"),
        ("RISK_ON", "Risk On"),
        ("MIXED", "Mixed"),
    ]

    timeframe = models.ForeignKey(
        Timeframe,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="regime_states",
    )
    regime = models.CharField(max_length=30, choices=REGIME_CHOICES, db_index=True)
    confidence = models.FloatField(default=0.0)

    trend_score = models.FloatField(default=0.0)
    volatility_score = models.FloatField(default=0.0)
    breadth_score = models.FloatField(default=0.0)
    correlation_stress_score = models.FloatField(default=0.0)

    summary = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.regime} ({self.confidence:.2f})"


class LearningSnapshot(TimeStampedModel):
    strategy = models.ForeignKey(
        Strategy,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="learning_snapshots",
    )
    asset = models.ForeignKey(
        Asset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="learning_snapshots",
    )
    timeframe = models.ForeignKey(
        Timeframe,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="learning_snapshots",
    )

    total_trades = models.PositiveIntegerField(default=0)
    wins = models.PositiveIntegerField(default=0)
    losses = models.PositiveIntegerField(default=0)
    breakevens = models.PositiveIntegerField(default=0)

    win_rate = models.FloatField(default=0.0)
    avg_pnl = models.FloatField(default=0.0)
    avg_win = models.FloatField(default=0.0)
    avg_loss = models.FloatField(default=0.0)
    payoff_ratio = models.FloatField(default=0.0)
    expectancy = models.FloatField(default=0.0)
    sharpe_like = models.FloatField(default=0.0)
    drawdown_penalty = models.FloatField(default=0.0)

    confidence_multiplier = models.FloatField(default=1.0)
    risk_multiplier = models.FloatField(default=1.0)
    size_multiplier = models.FloatField(default=1.0)

    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["strategy", "asset", "timeframe"]),
        ]

    def __str__(self):
        return f"LearningSnapshot {self.id}"


class RiskPolicy(TimeStampedModel):
    portfolio = models.OneToOneField(
        Portfolio,
        on_delete=models.CASCADE,
        related_name="risk_policy",
    )

    max_daily_loss_percent = models.FloatField(default=3.0)
    max_weekly_loss_percent = models.FloatField(default=7.0)
    max_drawdown_percent = models.FloatField(default=12.0)

    max_open_positions = models.PositiveIntegerField(default=5)
    max_positions_per_asset = models.PositiveIntegerField(default=1)
    max_correlated_positions = models.PositiveIntegerField(default=3)

    base_risk_per_trade_percent = models.FloatField(default=1.0)
    min_risk_per_trade_percent = models.FloatField(default=0.25)
    max_risk_per_trade_percent = models.FloatField(default=2.0)

    allow_auto_compounding = models.BooleanField(default=True)
    compounding_cap_percent = models.FloatField(default=50.0)

    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"RiskPolicy {self.portfolio.name}"


class RiskState(TimeStampedModel):
    STATUS_CHOICES = [
        ("NORMAL", "Normal"),
        ("CAUTION", "Caution"),
        ("REDUCE", "Reduce"),
        ("BLOCK", "Block"),
    ]

    portfolio = models.ForeignKey(
        Portfolio,
        on_delete=models.CASCADE,
        related_name="risk_states",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="NORMAL", db_index=True)

    current_daily_pnl = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    current_weekly_pnl = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    current_drawdown_percent = models.FloatField(default=0.0)
    exposure_percent = models.FloatField(default=0.0)
    correlation_risk_score = models.FloatField(default=0.0)

    recommended_risk_percent = models.FloatField(default=1.0)
    allow_new_positions = models.BooleanField(default=True)
    reason = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.portfolio.name} - {self.status}"


class ConfidenceAssessment(TimeStampedModel):
    idea = models.OneToOneField(
        TradeIdea,
        on_delete=models.CASCADE,
        related_name="confidence_assessment",
    )

    raw_confidence = models.FloatField(default=0.0)
    regime_adjustment = models.FloatField(default=0.0)
    learning_adjustment = models.FloatField(default=0.0)
    risk_adjustment = models.FloatField(default=0.0)
    final_confidence = models.FloatField(default=0.0)

    sizing_score = models.FloatField(default=0.0)
    execution_priority = models.PositiveIntegerField(default=99)

    payload = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"ConfidenceAssessment idea={self.idea_id}"


class ReinforcementEvent(TimeStampedModel):
    EVENT_CHOICES = [
        ("TRADE_CLOSED", "Trade Closed"),
        ("IDEA_EXPIRED", "Idea Expired"),
        ("STOP_HIT", "Stop Hit"),
        ("TAKE_PROFIT_HIT", "Take Profit Hit"),
        ("MANUAL_REVIEW", "Manual Review"),
    ]

    idea = models.ForeignKey(
        TradeIdea,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reinforcement_events",
    )
    signal = models.ForeignKey(
        Signal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reinforcement_events",
    )
    strategy = models.ForeignKey(
        Strategy,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reinforcement_events",
    )

    event_type = models.CharField(max_length=30, choices=EVENT_CHOICES, db_index=True)
    reward_value = models.FloatField(default=0.0)
    penalty_value = models.FloatField(default=0.0)
    net_value = models.FloatField(default=0.0)

    context_payload = models.JSONField(default=dict, blank=True)
    result_payload = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.event_type} ({self.net_value})"