from __future__ import annotations
from decimal import Decimal
from django.conf import settings
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class MarketScanRun(TimeStampedModel):
    STATUS_CHOICES = [
        ("STARTED", "Started"),
        ("SUCCESS", "Success"),
        ("FAILED", "Failed"),
    ]

    source = models.CharField(max_length=50, db_index=True, default="SYSTEM")
    universe = models.CharField(max_length=120, blank=True, null=True)
    timeframe_code = models.CharField(max_length=20, db_index=True, default="5m")
    regime_snapshot = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="STARTED", db_index=True)
    message = models.TextField(blank=True, null=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at"]


class MarketOpportunity(TimeStampedModel):
    DIRECTION_CHOICES = [
        ("BUY", "Buy"),
        ("SELL", "Sell"),
        ("CALL", "Call"),
        ("PUT", "Put"),
    ]

    STATUS_CHOICES = [
        ("NEW", "New"),
        ("ACTIVE", "Active"),
        ("EXPIRED", "Expired"),
        ("CONSUMED", "Consumed"),
        ("REJECTED", "Rejected"),
    ]

    scan_run = models.ForeignKey(
        MarketScanRun,
        on_delete=models.CASCADE,
        related_name="opportunities",
    )
    asset = models.ForeignKey(
        "market.Asset",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="market_opportunities",
    )
    symbol = models.CharField(max_length=50, db_index=True)
    asset_name = models.CharField(max_length=150, blank=True, null=True)
    timeframe_code = models.CharField(max_length=20, db_index=True, default="5m")

    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES, db_index=True)
    entry_price = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0"))
    stop_loss = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    take_profit = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)

    confidence_score = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("0.0000"))
    setup_score = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("0.0000"))
    risk_score = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("0.0000"))
    reward_score = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("0.0000"))
    overall_score = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("0.0000"))

    regime_label = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    feature_snapshot = models.JSONField(default=dict, blank=True)
    explanation = models.TextField(blank=True, null=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="NEW", db_index=True)
    expires_at = models.DateTimeField(blank=True, null=True, db_index=True)

    class Meta:
        ordering = ["-overall_score", "-created_at"]
        indexes = [
            models.Index(fields=["symbol", "status"]),
            models.Index(fields=["timeframe_code", "status"]),
        ]

    def __str__(self):
        return f"{self.symbol} {self.direction} ({self.overall_score})"


class TradeRecommendation(TimeStampedModel):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("APPROVED_BY_AI", "Approved by AI"),
        ("APPROVED_BY_USER", "Approved by User"),
        ("REJECTED_BY_USER", "Rejected by User"),
        ("BLOCKED_BY_RISK", "Blocked by Risk"),
        ("REDUCED_BY_RISK", "Reduced by Risk"),
        ("EXECUTED", "Executed"),
        ("EXPIRED", "Expired"),
    ]

    RECOMMENDATION_TYPE_CHOICES = [
        ("WATCH", "Watch"),
        ("PLAN", "Plan"),
        ("EXECUTE", "Execute"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trade_recommendations",
    )
    portfolio = models.ForeignKey(
        "portfolio.Portfolio",
        on_delete=models.CASCADE,
        related_name="trade_recommendations",
    )
    broker_account = models.ForeignKey(
        "brokers.BrokerAccount",
        on_delete=models.CASCADE,
        related_name="trade_recommendations",
    )
    opportunity = models.ForeignKey(
        MarketOpportunity,
        on_delete=models.CASCADE,
        related_name="recommendations",
    )

    recommendation_type = models.CharField(max_length=20, choices=RECOMMENDATION_TYPE_CHOICES, default="PLAN")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="PENDING", db_index=True)

    stake_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    recommended_quantity = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0"))
    recommended_notional = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    expected_risk_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    expected_reward_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    risk_reward_ratio = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("0.0000"))

    ai_confidence = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("0.0000"))
    ai_summary = models.TextField(blank=True, null=True)
    decision_payload = models.JSONField(default=dict, blank=True)

    approved_at = models.DateTimeField(blank=True, null=True)
    executed_at = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["portfolio", "status"]),
        ]

    def __str__(self):
        return f"{self.user} - {self.opportunity.symbol} - {self.status}"


class AIModelRegistry(TimeStampedModel):
    MODEL_TYPE_CHOICES = [
        ("LLM", "LLM"),
        ("CLASSIFIER", "Classifier"),
        ("RANKER", "Ranker"),
        ("REGIME", "Regime"),
        ("SCORER", "Scorer"),
    ]

    name = models.CharField(max_length=120, db_index=True)
    provider = models.CharField(max_length=120, db_index=True)
    model_name = models.CharField(max_length=120, db_index=True)
    version = models.CharField(max_length=50, db_index=True)
    model_type = models.CharField(max_length=30, choices=MODEL_TYPE_CHOICES, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["name", "-created_at"]
        unique_together = [("provider", "model_name", "version")]

    def __str__(self):
        return f"{self.provider}:{self.model_name}:{self.version}"


class AIInferenceLog(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_inference_logs",
    )
    portfolio = models.ForeignKey(
        "portfolio.Portfolio",
        on_delete=models.CASCADE,
        related_name="ai_inference_logs",
    )
    model = models.ForeignKey(
        AIModelRegistry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inference_logs",
    )
    prompt_hash = models.CharField(max_length=128, db_index=True)
    input_payload = models.JSONField(default=dict, blank=True)
    output_payload = models.JSONField(default=dict, blank=True)
    latency_ms = models.PositiveIntegerField(default=0)
    cost_estimate = models.DecimalField(max_digits=12, decimal_places=6, default=Decimal("0.000000"))
    success = models.BooleanField(default=True, db_index=True)
    error_message = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]


class DecisionAudit(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="decision_audits",
    )
    portfolio = models.ForeignKey(
        "portfolio.Portfolio",
        on_delete=models.CASCADE,
        related_name="decision_audits",
    )

    opportunity = models.ForeignKey(
        MarketOpportunity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="decision_audits",
    )
    recommendation = models.ForeignKey(
        TradeRecommendation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="decision_audits",
    )
    risk_decision = models.ForeignKey(
        "risk.RiskDecision",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="decision_audits",
    )
    order = models.ForeignKey(
        "execution.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="decision_audits",
    )

    ai_output = models.JSONField(default=dict, blank=True)
    sizing_output = models.JSONField(default=dict, blank=True)
    risk_output = models.JSONField(default=dict, blank=True)
    execution_output = models.JSONField(default=dict, blank=True)

    final_decision = models.CharField(max_length=50, db_index=True, default="PENDING")
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["portfolio", "final_decision"]),
        ]