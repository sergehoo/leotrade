"""
tests_phase/test_kill_switch.py
================================

Couverture : logique kill switch de bout en bout.

Scénarios :
  1. trigger_kill_switch() crée un KillSwitchEvent actif et met à jour
     les états journalier/hebdomadaire.
  2. has_active_kill_switch() retourne True après déclenchement.
  3. validate_trade() est bloqué en LIVE (HARD) mais laisse passer en DEMO/PAPER
     avec un warning dans le payload.
  4. resolve_kill_switch() désactive tous les events actifs.
  5. Après résolution, validate_trade() approuve à nouveau en LIVE.
  6. Déclenchement automatique sur dépassement de perte journalière
     (kill_switch_enabled=True dans le profil).
"""

from decimal import Decimal
from unittest import mock

import pytest
from django.utils import timezone

from risk.models import KillSwitchEvent, DailyRiskState, WeeklyRiskState
from risk.services import RiskGuardService, RiskStateService

# ── Paramètres de trade neutres ───────────────────────────────────────────────

TRADE_KWARGS = dict(
    symbol="R_100",
    side="BUY",
    requested_stake=Decimal("10.00"),
    approved_quantity=Decimal("1"),
    approved_notional=Decimal("10.00"),
    entry_price=Decimal("100.00"),
    stop_loss=None,
    take_profit=Decimal("110.00"),
    confidence=Decimal("0.95"),
    risk_override=False,
)


# ─────────────────────────────────────────────────────────────────────────────
#  1. Déclenchement
# ─────────────────────────────────────────────────────────────────────────────

class TestKillSwitchTrigger:

    @pytest.mark.django_db
    def test_trigger_creates_active_event(self, portfolio_live, risk_profile_live):
        """trigger_kill_switch() crée un KillSwitchEvent is_active=True."""
        assert not KillSwitchEvent.objects.filter(portfolio=portfolio_live).exists()

        RiskStateService.trigger_kill_switch(
            portfolio_live,
            risk_profile_live,
            reason_code="DAILY_LOSS_LIMIT",
            reason="Perte journalière atteinte.",
            payload={},
        )

        events = KillSwitchEvent.objects.filter(portfolio=portfolio_live)
        assert events.count() == 1
        assert events.first().is_active is True
        assert events.first().reason_code == "DAILY_LOSS_LIMIT"

    @pytest.mark.django_db
    def test_trigger_marks_daily_state_blocked(self, portfolio_live, risk_profile_live):
        """trigger_kill_switch() met kill_switch_triggered=True sur DailyRiskState."""
        RiskStateService.trigger_kill_switch(
            portfolio_live,
            risk_profile_live,
            reason_code="DAILY_LOSS_LIMIT",
            reason="test",
            payload={},
        )

        daily = DailyRiskState.objects.filter(
            portfolio=portfolio_live,
            day=timezone.localdate(),
        ).first()
        assert daily is not None
        assert daily.kill_switch_triggered is True
        assert daily.blocked_new_positions is True

    @pytest.mark.django_db
    def test_trigger_marks_weekly_state_blocked(self, portfolio_live, risk_profile_live):
        """trigger_kill_switch() met kill_switch_triggered=True sur WeeklyRiskState."""
        RiskStateService.trigger_kill_switch(
            portfolio_live,
            risk_profile_live,
            reason_code="WEEKLY_LOSS_LIMIT",
            reason="test",
            payload={},
        )

        from datetime import date, timedelta
        week_start = date.today() - timedelta(days=date.today().weekday())
        weekly = WeeklyRiskState.objects.filter(
            portfolio=portfolio_live,
            week_start=week_start,
        ).first()
        assert weekly is not None
        assert weekly.kill_switch_triggered is True

    @pytest.mark.django_db
    def test_has_active_kill_switch_true_after_trigger(
        self, portfolio_live, risk_profile_live
    ):
        """has_active_kill_switch() → True après un trigger."""
        assert not RiskGuardService.has_active_kill_switch(portfolio_live)

        RiskStateService.trigger_kill_switch(
            portfolio_live,
            risk_profile_live,
            reason_code="DAILY_LOSS_LIMIT",
            reason="test",
            payload={},
        )

        portfolio_live.refresh_from_db()
        assert RiskGuardService.has_active_kill_switch(portfolio_live)


# ─────────────────────────────────────────────────────────────────────────────
#  2. Comportement LIVE : bloquant (HARD)
# ─────────────────────────────────────────────────────────────────────────────

class TestKillSwitchBlocksLive:

    @pytest.mark.django_db
    def test_validate_trade_blocked_hard_in_live(
        self, portfolio_live, risk_profile_live
    ):
        """Kill switch actif → BLOCK HARD sur validate_trade() en LIVE."""
        KillSwitchEvent.objects.create(
            portfolio=portfolio_live,
            reason_code="DAILY_LOSS_LIMIT",
            reason="test",
            is_active=True,
            triggered_at=timezone.now(),
        )

        result = RiskGuardService.validate_trade(
            portfolio=portfolio_live,
            **TRADE_KWARGS,
        )

        assert result.decision == "BLOCK"
        assert result.block_code == "KILL_SWITCH_LIVE"
        assert result.block_severity == "HARD"

    @pytest.mark.django_db
    def test_kill_switch_live_unblockable_by_override(
        self, portfolio_live, risk_profile_live
    ):
        """Même avec risk_override=True, KILL_SWITCH_LIVE reste HARD."""
        KillSwitchEvent.objects.create(
            portfolio=portfolio_live,
            reason_code="DAILY_LOSS_LIMIT",
            reason="test",
            is_active=True,
            triggered_at=timezone.now(),
        )

        result = RiskGuardService.validate_trade(
            portfolio=portfolio_live,
            risk_override=True,
            risk_override_reason="tentative",
            risk_override_user_id=1,
            **{k: v for k, v in TRADE_KWARGS.items() if k != "risk_override"},
        )

        assert result.decision == "BLOCK"
        assert result.block_code == "KILL_SWITCH_LIVE"
        assert result.block_severity == "HARD"


# ─────────────────────────────────────────────────────────────────────────────
#  3. Comportement DEMO/PAPER : non-bloquant (warning dans payload)
# ─────────────────────────────────────────────────────────────────────────────

class TestKillSwitchNonBlockingDemo:

    @pytest.mark.django_db
    def test_kill_switch_does_not_block_paper(
        self, portfolio_paper, risk_profile_paper
    ):
        """Kill switch actif → APPROVE en PAPER avec warning dans payload."""
        KillSwitchEvent.objects.create(
            portfolio=portfolio_paper,
            reason_code="DAILY_LOSS_LIMIT",
            reason="test",
            is_active=True,
            triggered_at=timezone.now(),
        )

        result = RiskGuardService.validate_trade(
            portfolio=portfolio_paper,
            **TRADE_KWARGS,
        )

        # En PAPER le kill switch n'est pas bloquant
        assert result.decision == "APPROVE"
        # Mais un warning doit être présent dans le payload
        assert "kill_switch_warning" in result.payload

    @pytest.mark.django_db
    def test_kill_switch_warning_message_in_payload(
        self, portfolio_paper, risk_profile_paper
    ):
        """Le message de warning kill switch mentionne PAPER/DEMO."""
        KillSwitchEvent.objects.create(
            portfolio=portfolio_paper,
            reason_code="DAILY_LOSS_LIMIT",
            reason="test",
            is_active=True,
            triggered_at=timezone.now(),
        )

        result = RiskGuardService.validate_trade(
            portfolio=portfolio_paper,
            **TRADE_KWARGS,
        )

        warning = result.payload.get("kill_switch_warning", "")
        assert warning  # non vide
        # Le message doit indiquer que c'est non-bloquant car PAPER/DEMO
        assert "PAPER" in warning.upper() or "DEMO" in warning.upper()


# ─────────────────────────────────────────────────────────────────────────────
#  4. Résolution du kill switch
# ─────────────────────────────────────────────────────────────────────────────

class TestKillSwitchResolution:

    @pytest.mark.django_db
    def test_resolve_deactivates_all_active_events(
        self, portfolio_live, risk_profile_live
    ):
        """resolve_kill_switch() met is_active=False sur tous les events actifs."""
        # Créer 2 events actifs
        for i in range(2):
            KillSwitchEvent.objects.create(
                portfolio=portfolio_live,
                reason_code="DAILY_LOSS_LIMIT",
                reason=f"test {i}",
                is_active=True,
                triggered_at=timezone.now(),
            )

        assert KillSwitchEvent.objects.filter(
            portfolio=portfolio_live, is_active=True
        ).count() == 2

        RiskStateService.resolve_kill_switch(portfolio_live)

        assert KillSwitchEvent.objects.filter(
            portfolio=portfolio_live, is_active=True
        ).count() == 0
        assert KillSwitchEvent.objects.filter(
            portfolio=portfolio_live, is_active=False
        ).count() == 2

    @pytest.mark.django_db
    def test_has_active_kill_switch_false_after_resolve(
        self, portfolio_live, risk_profile_live
    ):
        """has_active_kill_switch() → False après resolve."""
        KillSwitchEvent.objects.create(
            portfolio=portfolio_live,
            reason_code="DAILY_LOSS_LIMIT",
            reason="test",
            is_active=True,
            triggered_at=timezone.now(),
        )

        RiskStateService.resolve_kill_switch(portfolio_live)
        portfolio_live.refresh_from_db()

        assert not RiskGuardService.has_active_kill_switch(portfolio_live)

    @pytest.mark.django_db
    def test_trade_approved_after_resolve(self, portfolio_live, risk_profile_live):
        """Après resolve, validate_trade() approuve en LIVE."""
        KillSwitchEvent.objects.create(
            portfolio=portfolio_live,
            reason_code="DAILY_LOSS_LIMIT",
            reason="test",
            is_active=True,
            triggered_at=timezone.now(),
        )

        # Bloqué avant resolve
        result_before = RiskGuardService.validate_trade(
            portfolio=portfolio_live, **TRADE_KWARGS
        )
        assert result_before.decision == "BLOCK"
        assert result_before.block_code == "KILL_SWITCH_LIVE"

        # Résoudre
        RiskStateService.resolve_kill_switch(portfolio_live)
        portfolio_live.refresh_from_db()

        # Approuvé après resolve
        result_after = RiskGuardService.validate_trade(
            portfolio=portfolio_live, **TRADE_KWARGS
        )
        assert result_after.decision == "APPROVE"


# ─────────────────────────────────────────────────────────────────────────────
#  5. Déclenchement automatique sur dépassement de perte journalière
# ─────────────────────────────────────────────────────────────────────────────

class TestKillSwitchAutoTrigger:

    @pytest.mark.django_db
    def test_daily_loss_auto_triggers_kill_switch(
        self, portfolio_live, risk_profile_live
    ):
        """Quand la perte journalière dépasse max_daily_loss ET kill_switch_enabled=True,
        validate_trade() déclenche automatiquement le kill switch."""
        risk_profile_live.max_daily_loss = Decimal("1.00")
        risk_profile_live.kill_switch_enabled = True
        risk_profile_live.save()

        DailyRiskState.objects.update_or_create(
            portfolio=portfolio_live,
            day=timezone.localdate(),
            defaults={
                "total_loss_percent": Decimal("5.00"),
                "total_loss_amount": Decimal("500.00"),
                "equity_open": Decimal("10000.00"),
                "equity_current": Decimal("9500.00"),
            },
        )

        # Avant : aucun kill switch actif
        assert not RiskGuardService.has_active_kill_switch(portfolio_live)

        RiskGuardService.validate_trade(
            portfolio=portfolio_live, **TRADE_KWARGS
        )

        # Après l'appel, le kill switch doit avoir été créé
        portfolio_live.refresh_from_db()
        assert RiskGuardService.has_active_kill_switch(portfolio_live)

    @pytest.mark.django_db
    def test_daily_loss_no_kill_switch_when_disabled(
        self, portfolio_live, risk_profile_live
    ):
        """Quand kill_switch_enabled=False, le dépassement de perte ne déclenche PAS
        le kill switch automatique."""
        risk_profile_live.max_daily_loss = Decimal("1.00")
        risk_profile_live.kill_switch_enabled = False
        risk_profile_live.save()

        DailyRiskState.objects.update_or_create(
            portfolio=portfolio_live,
            day=timezone.localdate(),
            defaults={
                "total_loss_percent": Decimal("5.00"),
                "total_loss_amount": Decimal("500.00"),
                "equity_open": Decimal("10000.00"),
                "equity_current": Decimal("9500.00"),
            },
        )

        RiskGuardService.validate_trade(
            portfolio=portfolio_live, **TRADE_KWARGS
        )

        portfolio_live.refresh_from_db()
        assert not RiskGuardService.has_active_kill_switch(portfolio_live)
