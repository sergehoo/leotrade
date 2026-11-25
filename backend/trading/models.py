from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone

from core.models import TimeStampedModel
from brokers.models import BrokerAccount
from market.models import Timeframe, Asset
from portfolio.models import Portfolio, Position
from strategies.models import Signal, Strategy

from .models_ai import (
    MarketScanRun,
    MarketOpportunity,
    TradeRecommendation,
    AIModelRegistry,
    AIInferenceLog,
    DecisionAudit,
)
User = get_user_model()


class TradingIntent(TimeStampedModel):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("ANALYZING", "Analyzing"),
        ("PLANNED", "Planned"),
        ("APPROVED", "Approved"),
        ("RUNNING", "Running"),
        ("COMPLETED", "Completed"),
        ("STOPPED", "Stopped"),
        ("REJECTED", "Rejected"),
        ("FAILED", "Failed"),
        ("EXPIRED", "Expired"),
    ]

    RISK_LEVEL_CHOICES = [
        ("LOW", "Low"),
        ("MEDIUM", "Medium"),
        ("HIGH", "High"),
        ("AGGRESSIVE", "Aggressive"),
    ]

    EXECUTION_MODE_CHOICES = [
        ("PAPER", "Paper"),
        ("LIVE", "Live"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="trading_intents")
    broker_account = models.ForeignKey(
        BrokerAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trading_intents",
    )
    portfolio = models.ForeignKey(
        Portfolio,
        on_delete=models.CASCADE,
        related_name="trading_intents",
    )
    strategy = models.ForeignKey(
        Strategy,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trading_intents",
    )

    title = models.CharField(max_length=200)
    objective_prompt = models.TextField(blank=True)

    capital_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    allocated_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    capital_currency = models.CharField(max_length=10, default="USD")

    target_return_percent = models.FloatField(default=0.0)
    max_loss_percent = models.FloatField(default=0.0)
    duration_days = models.PositiveIntegerField(default=1)
    max_open_positions = models.PositiveIntegerField(default=3)

    risk_level = models.CharField(max_length=20, choices=RISK_LEVEL_CHOICES, default="MEDIUM")
    execution_mode = models.CharField(max_length=10, choices=EXECUTION_MODE_CHOICES, default="PAPER")
    allowed_asset_classes = models.JSONField(default=list, blank=True)

    ai_feasibility_score = models.FloatField(default=0.0)
    ai_analysis = models.JSONField(default=dict, blank=True)
    ai_plan = models.JSONField(default=dict, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="DRAFT", db_index=True)
    rejection_reason = models.TextField(blank=True)
    approved_by_user = models.BooleanField(default=False)

    realized_pnl = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    unrealized_pnl = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    actual_return_percent = models.FloatField(default=0.0)

    started_at = models.DateTimeField(blank=True, null=True)
    ended_at = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["portfolio", "status"]),
        ]

    def __str__(self):
        return self.title

    @property
    def is_live(self):
        return self.execution_mode == "LIVE"

    @property
    def is_running(self):
        return self.status == "RUNNING"


class TradingIntentEvent(TimeStampedModel):
    EVENT_TYPE_CHOICES = [
        ("CREATED", "Created"),
        ("ANALYZED", "Analyzed"),
        ("PLANNED", "Planned"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("STARTED", "Started"),
        ("ORDER_CREATED", "Order Created"),
        ("POSITION_OPENED", "Position Opened"),
        ("POSITION_CLOSED", "Position Closed"),
        ("COMPLETED", "Completed"),
        ("STOPPED", "Stopped"),
        ("FAILED", "Failed"),
    ]

    intent = models.ForeignKey(TradingIntent, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=30, choices=EVENT_TYPE_CHOICES, db_index=True)
    title = models.CharField(max_length=200, blank=True)
    message = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.intent.title} - {self.event_type}"


class Order(TimeStampedModel):
    SIDE_CHOICES = [
        ("BUY", "Buy"),
        ("SELL", "Sell"),
    ]
    TYPE_CHOICES = [
        ("MARKET", "Market"),
        ("LIMIT", "Limit"),
        ("STOP", "Stop"),
    ]
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("PLACED", "Placed"),
        ("FILLED", "Filled"),
        ("PARTIALLY_FILLED", "Partially Filled"),
        ("CANCELLED", "Cancelled"),
        ("REJECTED", "Rejected"),
        ("FAILED", "Failed"),
    ]
    TIF_CHOICES = [
        ("GTC", "Good Till Cancelled"),
        ("IOC", "Immediate Or Cancel"),
        ("FOK", "Fill Or Kill"),
    ]

    broker_account = models.ForeignKey(BrokerAccount, on_delete=models.CASCADE, related_name="orders")
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name="orders")
    intent = models.ForeignKey(
        TradingIntent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    signal = models.ForeignKey(Signal, on_delete=models.SET_NULL, null=True, blank=True, related_name="orders")
    position = models.ForeignKey(Position, on_delete=models.SET_NULL, null=True, blank=True, related_name="orders")

    symbol = models.CharField(max_length=30, db_index=True)
    side = models.CharField(max_length=10, choices=SIDE_CHOICES)
    order_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default="MARKET")
    time_in_force = models.CharField(max_length=10, choices=TIF_CHOICES, default="GTC")

    quantity = models.DecimalField(max_digits=24, decimal_places=10)
    filled_quantity = models.DecimalField(max_digits=24, decimal_places=10, default=Decimal("0"))
    price = models.DecimalField(max_digits=24, decimal_places=10, blank=True, null=True)
    average_fill_price = models.DecimalField(max_digits=24, decimal_places=10, blank=True, null=True)

    stop_loss = models.DecimalField(max_digits=24, decimal_places=10, blank=True, null=True)
    take_profit = models.DecimalField(max_digits=24, decimal_places=10, blank=True, null=True)

    client_order_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    external_order_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="PENDING", db_index=True)

    placed_at = models.DateTimeField(blank=True, null=True)
    filled_at = models.DateTimeField(blank=True, null=True)
    cancelled_at = models.DateTimeField(blank=True, null=True)

    broker_payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["portfolio", "status"]),
            models.Index(fields=["symbol", "status"]),
        ]

    def __str__(self):
        return f"{self.symbol} {self.side} {self.quantity}"


class TradeExecution(TimeStampedModel):
    LIQUIDITY_CHOICES = [
        ("MAKER", "Maker"),
        ("TAKER", "Taker"),
    ]

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="executions")
    execution_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)

    execution_price = models.DecimalField(max_digits=24, decimal_places=10)
    execution_qty = models.DecimalField(max_digits=24, decimal_places=10)
    fee = models.DecimalField(max_digits=24, decimal_places=10, default=Decimal("0"))
    fee_asset = models.CharField(max_length=20, blank=True, null=True)
    liquidity = models.CharField(max_length=20, choices=LIQUIDITY_CHOICES, blank=True, null=True)

    executed_at = models.DateTimeField(default=timezone.now)
    broker_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-executed_at"]

    def __str__(self):
        return f"Execution {self.order_id} @ {self.execution_price}"


class DerivContract(TimeStampedModel):
    STATUS_CHOICES = [
        ("OPEN", "Open"),
        ("WON", "Won"),
        ("LOST", "Lost"),
        ("SOLD", "Sold"),
        ("CANCELLED", "Cancelled"),
        ("EXPIRED", "Expired"),
        ("FAILED", "Failed"),
    ]

    order = models.OneToOneField(
        "Order",
        on_delete=models.CASCADE,
        related_name="deriv_contract",
    )
    broker_account = models.ForeignKey(
        BrokerAccount,
        on_delete=models.CASCADE,
        related_name="deriv_contracts",
    )
    portfolio = models.ForeignKey(
        Portfolio,
        on_delete=models.CASCADE,
        related_name="deriv_contracts",
    )
    signal = models.ForeignKey(
        Signal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deriv_contracts",
    )

    contract_id = models.CharField(max_length=100, unique=True, db_index=True)
    transaction_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    symbol = models.CharField(max_length=50, db_index=True)
    contract_type = models.CharField(max_length=30)
    duration = models.PositiveIntegerField(default=5)
    duration_unit = models.CharField(max_length=10, default="m")
    currency = models.CharField(max_length=10, default="USD")

    buy_price = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    payout = models.DecimalField(max_digits=18, decimal_places=2, blank=True, null=True)
    profit = models.DecimalField(max_digits=18, decimal_places=2, blank=True, null=True)
    entry_tick = models.DecimalField(max_digits=24, decimal_places=10, blank=True, null=True)
    exit_tick = models.DecimalField(max_digits=24, decimal_places=10, blank=True, null=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="OPEN", db_index=True)
    is_expired = models.BooleanField(default=False)
    is_sold = models.BooleanField(default=False)

    purchased_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(blank=True, null=True)
    settled_at = models.DateTimeField(blank=True, null=True)

    proposal_payload = models.JSONField(default=dict, blank=True)
    buy_payload = models.JSONField(default=dict, blank=True)
    latest_contract_payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "is_expired"]),
            models.Index(fields=["symbol", "status"]),
        ]

    def __str__(self):
        return f"{self.symbol} {self.contract_type} #{self.contract_id}"



class TradeIdea(TimeStampedModel):
    DIRECTION_CHOICES = [
        ("BUY", "Buy"),
        ("SELL", "Sell"),
        ("CALL", "Call"),
        ("PUT", "Put"),
    ]

    STATUS_CHOICES = [
        ("NEW", "New"),
        ("REVIEW", "Review"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("EXECUTED", "Executed"),
        ("EXPIRED", "Expired"),
        ("CANCELLED", "Cancelled"),
    ]

    SOURCE_CHOICES = [
        ("RULE", "Rule"),
        ("ML", "Machine Learning"),
        ("HYBRID", "Hybrid"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trade_ideas",
        null=False,
        blank=False,
    )
    scan_run = models.ForeignKey(
        MarketScanRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trade_ideas",
    )

    asset = models.ForeignKey(
        Asset,
        on_delete=models.CASCADE,
        related_name="trade_ideas",
    )
    timeframe = models.ForeignKey(
        Timeframe,
        on_delete=models.CASCADE,
        related_name="trade_ideas",
    )
    strategy = models.ForeignKey(
        Strategy,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trade_ideas",
    )
    signal = models.ForeignKey(
        Signal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trade_ideas",
    )

    source_type = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="HYBRID")
    symbol = models.CharField(max_length=50, db_index=True)
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES, db_index=True)

    entry_price = models.DecimalField(max_digits=24, decimal_places=10, null=True, blank=True)
    stop_loss = models.DecimalField(max_digits=24, decimal_places=10, null=True, blank=True)
    take_profit = models.DecimalField(max_digits=24, decimal_places=10, null=True, blank=True)

    horizon_minutes = models.PositiveIntegerField(default=60)
    expected_rr = models.FloatField(default=0.0)

    confidence_score = models.FloatField(default=0.0)
    setup_score = models.FloatField(default=0.0)
    risk_score = models.FloatField(default=0.0)
    reward_score = models.FloatField(default=0.0)
    overall_score = models.FloatField(default=0.0)

    market_snapshot = models.JSONField(default=dict, blank=True)
    features_snapshot = models.JSONField(default=dict, blank=True)
    explanation = models.TextField(blank=True)
    ai_payload = models.JSONField(default=dict, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="NEW", db_index=True)
    auto_trade_enabled = models.BooleanField(default=False)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-overall_score", "-created_at"]
        indexes = [
            models.Index(fields=["status", "overall_score"]),
            models.Index(fields=["symbol", "status"]),
            models.Index(fields=["asset", "timeframe", "status"]),
        ]

    def __str__(self):
        return f"{self.symbol} {self.direction} ({self.overall_score:.2f})"

    @property
    def is_expired(self):
        return self.expires_at and timezone.now() >= self.expires_at


class TradeIdeaFeedback(TimeStampedModel):
    OUTCOME_CHOICES = [
        ("WIN", "Win"),
        ("LOSS", "Loss"),
        ("BREAKEVEN", "Breakeven"),
        ("OPEN", "Open"),
        ("MISSED", "Missed"),
    ]

    idea = models.OneToOneField(
        TradeIdea,
        on_delete=models.CASCADE,
        related_name="feedback",
    )

    signal = models.ForeignKey(
        Signal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="idea_feedbacks",
    )

    order_id = models.CharField(max_length=100, blank=True)
    execution_status = models.CharField(max_length=30, blank=True)
    outcome = models.CharField(max_length=20, choices=OUTCOME_CHOICES, default="OPEN")

    pnl_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    pnl_percent = models.FloatField(default=0.0)
    hit_take_profit = models.BooleanField(default=False)
    hit_stop_loss = models.BooleanField(default=False)

    execution_latency_ms = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)
    learning_payload = models.JSONField(default=dict, blank=True)
    evaluated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Feedback {self.idea_id} - {self.outcome}"

class AgentRun(TimeStampedModel):
    AGENT_CHOICES = [
        ("MARKET_REGIME", "Market Regime Agent"),
        ("TRADE_IDEA_REVIEW", "Trade Idea Review Agent"),
        ("PORTFOLIO_ADVISOR", "Portfolio Advisor Agent"),
    ]

    STATUS_CHOICES = [
        ("RUNNING", "Running"),
        ("SUCCEEDED", "Succeeded"),
        ("FAILED", "Failed"),
    ]

    agent_type = models.CharField(max_length=50, choices=AGENT_CHOICES, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="RUNNING", db_index=True)

    market_scan_run = models.ForeignKey(
        "MarketScanRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_runs",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_runs",
    )

    input_payload = models.JSONField(default=dict, blank=True)
    output_payload = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)
    error_message = models.TextField(blank=True)

    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(blank=True, null=True)
    runtime_ms = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.agent_type} - {self.status}"


class MarketRegimeSnapshot(TimeStampedModel):
    REGIME_CHOICES = [
        ("TREND_BULLISH", "Trend Bullish"),
        ("TREND_BEARISH", "Trend Bearish"),
        ("RANGE", "Range"),
        ("VOLATILE", "Volatile"),
        ("MIXED", "Mixed"),
    ]

    market_scan_run = models.ForeignKey(
        "MarketScanRun",
        on_delete=models.CASCADE,
        related_name="regime_snapshots",
    )
    timeframe = models.ForeignKey(
        "market.Timeframe",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="regime_snapshots",
    )

    regime = models.CharField(max_length=30, choices=REGIME_CHOICES, default="MIXED", db_index=True)
    confidence = models.FloatField(default=0.0)
    summary = models.TextField(blank=True)
    risk_posture = models.CharField(max_length=30, default="NEUTRAL")
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.regime} ({self.confidence:.2f})"


class TradeIdeaReview(TimeStampedModel):
    DECISION_CHOICES = [
        ("APPROVE", "Approve"),
        ("REJECT", "Reject"),
        ("REVIEW", "Review"),
    ]

    idea = models.OneToOneField(
        "TradeIdea",
        on_delete=models.CASCADE,
        related_name="review",
    )
    agent_run = models.ForeignKey(
        "AgentRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="idea_reviews",
    )

    decision = models.CharField(max_length=20, choices=DECISION_CHOICES, default="REVIEW")
    priority = models.PositiveIntegerField(default=99)
    confidence_adjustment = models.FloatField(default=0.0)
    adjusted_score = models.FloatField(default=0.0)

    reasoning = models.TextField(blank=True)
    portfolio_fit_score = models.FloatField(default=0.0)
    market_alignment_score = models.FloatField(default=0.0)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["priority", "-adjusted_score", "-created_at"]

    def __str__(self):
        return f"Idea {self.idea_id} - {self.decision}"


class PortfolioAdvice(TimeStampedModel):
    ACTION_CHOICES = [
        ("ALLOW_NEW_POSITIONS", "Allow New Positions"),
        ("REDUCE_RISK", "Reduce Risk"),
        ("BLOCK_NEW_POSITIONS", "Block New Positions"),
        ("CLOSE_WEAK_POSITIONS", "Close Weak Positions"),
    ]

    portfolio = models.ForeignKey(
        "portfolio.Portfolio",
        on_delete=models.CASCADE,
        related_name="portfolio_advices",
    )
    agent_run = models.ForeignKey(
        "AgentRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="portfolio_advices",
    )

    action = models.CharField(max_length=30, choices=ACTION_CHOICES, default="ALLOW_NEW_POSITIONS")
    confidence = models.FloatField(default=0.0)
    max_new_positions = models.PositiveIntegerField(default=1)
    recommended_risk_percent = models.FloatField(default=1.0)
    summary = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.portfolio.name} - {self.action}"