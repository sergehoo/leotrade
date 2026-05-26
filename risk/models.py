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


class RiskProfile(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="risk_profiles",
    )
    portfolio = models.ForeignKey(
        "portfolio.Portfolio",
        on_delete=models.CASCADE,
        related_name="risk_profiles",
    )

    name = models.CharField(max_length=120, default="Default Risk Profile")
    is_active = models.BooleanField(default=True, db_index=True)
    is_default = models.BooleanField(default=True, db_index=True)

    max_risk_per_trade = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("1.00"))
    max_daily_loss = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("3.00"))
    max_weekly_loss = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("6.00"))
    max_drawdown = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("10.00"))

    max_open_positions = models.PositiveIntegerField(default=5)
    max_symbol_exposure_percent = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("25.00"))
    max_asset_class_exposure_percent = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("50.00"))
    max_correlated_exposure_percent = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("40.00"))

    max_leverage = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("3.00"))
    min_confidence = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("0.60"))

    allow_short = models.BooleanField(default=False)
    allow_live_trading = models.BooleanField(default=True)
    require_stop_loss = models.BooleanField(default=True)
    block_on_high_correlation = models.BooleanField(default=True)

    kill_switch_enabled = models.BooleanField(default=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["portfolio_id", "-is_default", "name"]
        unique_together = [("portfolio", "name")]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["portfolio", "is_default"]),
        ]

    def __str__(self):
        return f"{self.portfolio.name} - {self.name}"


class DailyRiskState(TimeStampedModel):
    portfolio = models.ForeignKey(
        "portfolio.Portfolio",
        on_delete=models.CASCADE,
        related_name="daily_risk_states",
    )
    day = models.DateField(db_index=True)

    realized_pnl = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    unrealized_pnl = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    total_loss_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    total_loss_percent = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("0.00"))

    equity_open = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    equity_current = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    open_positions_count = models.PositiveIntegerField(default=0)
    blocked_new_positions = models.BooleanField(default=False)
    kill_switch_triggered = models.BooleanField(default=False)

    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = [("portfolio", "day")]
        ordering = ["-day"]


class WeeklyRiskState(TimeStampedModel):
    portfolio = models.ForeignKey(
        "portfolio.Portfolio",
        on_delete=models.CASCADE,
        related_name="weekly_risk_states",
    )
    week_start = models.DateField(db_index=True)

    realized_pnl = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    unrealized_pnl = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    total_loss_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    total_loss_percent = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("0.00"))

    equity_open = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    equity_current = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    blocked_new_positions = models.BooleanField(default=False)
    kill_switch_triggered = models.BooleanField(default=False)

    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = [("portfolio", "week_start")]
        ordering = ["-week_start"]


class RiskDecision(TimeStampedModel):
    DECISION_CHOICES = [
        ("APPROVE", "Approve"),
        ("REDUCE", "Reduce"),
        ("REJECT", "Reject"),
        ("BLOCK", "Block"),
    ]

    portfolio = models.ForeignKey(
        "portfolio.Portfolio",
        on_delete=models.CASCADE,
        related_name="risk_decisions",
    )
    risk_profile = models.ForeignKey(
        RiskProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="decisions",
    )

    signal = models.ForeignKey(
        "strategies.Signal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="risk_decisions",
    )
    trade_idea = models.ForeignKey(
        "trading.TradeIdea",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="risk_decisions",
    )
    order = models.ForeignKey(
        "execution.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="risk_decisions",
    )

    symbol = models.CharField(max_length=50, db_index=True)
    asset_class = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    side = models.CharField(max_length=10, blank=True, null=True)

    requested_stake = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    approved_stake = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    requested_quantity = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0"))
    approved_quantity = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0"))

    requested_notional = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    approved_notional = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    expected_loss = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    expected_gain = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    risk_reward_ratio = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("0.00"))

    decision = models.CharField(max_length=20, choices=DECISION_CHOICES, db_index=True)
    blocking_reason = models.TextField(blank=True, null=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["portfolio", "decision"]),
            models.Index(fields=["portfolio", "symbol"]),
        ]

    def __str__(self):
        return f"{self.portfolio.name} - {self.symbol} - {self.decision}"


class KillSwitchEvent(TimeStampedModel):
    portfolio = models.ForeignKey(
        "portfolio.Portfolio",
        on_delete=models.CASCADE,
        related_name="kill_switch_events",
    )
    risk_profile = models.ForeignKey(
        RiskProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="kill_switch_events",
    )

    reason_code = models.CharField(max_length=50, db_index=True)
    reason = models.TextField()
    triggered_at = models.DateTimeField(default=timezone.now, db_index=True)

    is_active = models.BooleanField(default=True, db_index=True)
    resolved_at = models.DateTimeField(blank=True, null=True)

    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-triggered_at"]
        indexes = [
            models.Index(fields=["portfolio", "is_active"]),
        ]

    def __str__(self):
        return f"{self.portfolio.name} - {self.reason_code}"


class RiskOverrideAudit(models.Model):
    """
    Trace immuable de chaque décharge de risque acceptée par un utilisateur.

    Créé automatiquement par RiskGuardService.validate_trade() lorsque
    risk_override=True et que le résultat final est APPROVE (i.e. au moins
    un contrôle SOFT a été franchi ou l'override a été explicitement déclaré).

    Ce modèle est en lecture seule depuis l'admin Django (pas d'add/change/delete).
    Il est exportable mensuellement en CSV pour archivage légal.

    Champs clés pour la traçabilité légale
    ----------------------------------------
    - user             : qui a passé outre
    - portfolio        : sur quel portefeuille
    - symbol / side    : quel trade
    - codes_bypassed   : liste des codes SOFT franchis (ex: ["MAX_OPEN_POSITIONS"])
    - reason           : texte libre saisi par l'utilisateur dans la décharge
    - ip_address       : adresse IP au moment de l'action
    - user_agent       : navigateur/client
    - overridden_at    : horodatage précis (immutable)
    - profile_snapshot : snapshot JSON du profil de risque au moment de l'override
                         (utile si le profil est modifié ultérieurement)
    - risk_decision    : FK vers la RiskDecision persistée (nullable : certains
                         appels n'ont pas encore persisté la décision)
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="risk_overrides",
        help_text="Utilisateur qui a accepté la décharge.",
    )
    portfolio = models.ForeignKey(
        "portfolio.Portfolio",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="risk_overrides",
    )
    risk_decision = models.ForeignKey(
        RiskDecision,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="overrides",
        help_text="Décision de risque associée (peut être nulle si non persistée).",
    )

    # ── Identité du trade ────────────────────────────────────────────────
    symbol = models.CharField(max_length=50, db_index=True)
    side = models.CharField(max_length=10, blank=True)
    requested_stake = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00")
    )

    # ── Codes franchis ───────────────────────────────────────────────────
    codes_bypassed = models.JSONField(
        default=list,
        help_text='Liste des codes SOFT franchis, ex: ["MAX_OPEN_POSITIONS", "DAILY_LOSS_LIMIT"].',
    )

    # ── Décharge utilisateur ─────────────────────────────────────────────
    reason = models.TextField(
        blank=True,
        help_text="Motif saisi par l'utilisateur dans le formulaire de décharge.",
    )

    # ── Contexte réseau ─────────────────────────────────────────────────
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP de l'utilisateur au moment de l'override.",
    )
    user_agent = models.TextField(
        blank=True,
        help_text="User-Agent HTTP de l'utilisateur.",
    )

    # ── Horodatage ────────────────────────────────────────────────────────
    overridden_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        help_text="Horodatage de la décharge (immutable).",
    )

    # ── Snapshot du profil ───────────────────────────────────────────────
    profile_snapshot = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Snapshot des paramètres du RiskProfile au moment de l'override. "
            "Permet de reconstituer le contexte si le profil évolue ensuite."
        ),
    )

    class Meta:
        ordering = ["-overridden_at"]
        indexes = [
            models.Index(fields=["user", "overridden_at"]),
            models.Index(fields=["portfolio", "overridden_at"]),
            models.Index(fields=["symbol", "overridden_at"]),
        ]
        verbose_name = "Risk Override Audit"
        verbose_name_plural = "Risk Override Audits"

    def __str__(self):
        user_str = str(self.user) if self.user else "?"
        codes = ", ".join(self.codes_bypassed) if self.codes_bypassed else "—"
        return f"Override [{user_str}] {self.symbol} {self.side} — {codes} — {self.overridden_at:%Y-%m-%d %H:%M}"

    @classmethod
    def record(
        cls,
        *,
        user_id,
        portfolio,
        symbol: str,
        side: str,
        requested_stake,
        codes_bypassed: list,
        reason: str,
        ip_address: str | None,
        user_agent: str,
        profile_snapshot: dict,
        risk_decision=None,
    ) -> "RiskOverrideAudit":
        """
        Crée un enregistrement d'audit. À appeler après une validation APPROVE
        avec risk_override=True.

        Fail-safe : si la création échoue (contrainte, etc.), on log l'erreur
        sans lever d'exception pour ne pas bloquer l'exécution du trade.
        """
        import logging
        log = logging.getLogger("leotrade.risk.audit")
        try:
            return cls.objects.create(
                user_id=user_id,
                portfolio=portfolio,
                risk_decision=risk_decision,
                symbol=symbol,
                side=side,
                requested_stake=requested_stake,
                codes_bypassed=codes_bypassed,
                reason=reason or "",
                ip_address=ip_address or None,
                user_agent=user_agent or "",
                profile_snapshot=profile_snapshot,
            )
        except Exception as exc:
            log.error(
                "risk_override_audit.record_failed user_id=%s symbol=%s err=%s",
                user_id, symbol, exc,
            )
            return None


# from decimal import Decimal
#
# from django.db import models
#
# from core.models import TimeStampedModel
# from portfolio.models import Portfolio
# from trading.models import TradeRecommendation
#
#
# class RiskProfile(TimeStampedModel):
#     portfolio = models.OneToOneField(Portfolio, on_delete=models.CASCADE, related_name="risk_profile")
#
#     max_risk_per_trade_percent = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("1.0000"))
#     max_daily_loss_percent = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("3.0000"))
#     max_weekly_loss_percent = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("8.0000"))
#
#     max_open_positions = models.PositiveIntegerField(default=5)
#     max_symbol_exposure_percent = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("20.0000"))
#     max_asset_class_exposure_percent = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("50.0000"))
#     max_correlated_exposure_percent = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("40.0000"))
#     max_leverage = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("5.00"))
#
#     allow_short = models.BooleanField(default=False)
#     allow_live_trading = models.BooleanField(default=False)
#     min_confidence_score = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("0.6000"))
#
#     def __str__(self) -> str:
#         return f"RiskProfile::{self.portfolio_id}"
#
#
# class RiskDecision(TimeStampedModel):
#     class Decision(models.TextChoices):
#         APPROVE = "APPROVE", "Approve"
#         REDUCE = "REDUCE", "Reduce"
#         REJECT = "REJECT", "Reject"
#
#     portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name="risk_decisions")
#     recommendation = models.ForeignKey(
#         TradeRecommendation,
#         on_delete=models.CASCADE,
#         related_name="risk_decisions",
#     )
#
#     decision = models.CharField(max_length=20, choices=Decision.choices, db_index=True)
#
#     requested_stake = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0"))
#     approved_stake = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0"))
#     approved_quantity = models.DecimalField(max_digits=24, decimal_places=10, default=Decimal("0"))
#     approved_notional = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0"))
#
#     expected_loss = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0"))
#     expected_gain = models.DecimalField(max_digits=24, decimal_places=8, default=Decimal("0"))
#
#     blocking_reason = models.TextField(blank=True)
#     payload = models.JSONField(default=dict, blank=True)
#
#     def __str__(self) -> str:
#         return f"RiskDecision::{self.recommendation_id}::{self.decision}"