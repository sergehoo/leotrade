"""
tests_phase/test_risk_override.py
==================================

Couverture : RiskGuardService.validate_trade() — logique d'override.

Règle fondamentale :
  • Blocage SOFT  → franchissable avec risk_override=True
  • Blocage HARD  → reste bloquant quoi qu'il arrive (kill switch LIVE,
                    live trading interdit, short interdit)

Codes SOFT testés :
  AI_CONFIDENCE_TOO_LOW, STOP_LOSS_REQUIRED, MAX_OPEN_POSITIONS,
  DAILY_LOSS_LIMIT, WEEKLY_LOSS_LIMIT

Codes HARD testés :
  KILL_SWITCH_LIVE, LIVE_TRADING_FORBIDDEN, SHORT_FORBIDDEN
"""

from decimal import Decimal
from unittest import mock

import pytest
from django.utils import timezone

from risk.models import KillSwitchEvent, RiskProfile
from risk.services import RiskGuardService

# ── Helpers locaux ────────────────────────────────────────────────────────────

COMMON_TRADE_KWARGS = dict(
    symbol="R_100",
    side="BUY",
    requested_stake=Decimal("10.00"),
    approved_quantity=Decimal("1"),
    approved_notional=Decimal("10.00"),
    entry_price=Decimal("100.00"),
    stop_loss=None,
    take_profit=Decimal("110.00"),
    confidence=Decimal("0.95"),
)


def _validate(portfolio, override=False, **overrides):
    """Raccourci pour appeler validate_trade avec les params du test."""
    kwargs = {**COMMON_TRADE_KWARGS, **overrides}
    return RiskGuardService.validate_trade(
        portfolio=portfolio,
        risk_override=override,
        risk_override_reason="test override" if override else "",
        risk_override_user_id=1 if override else None,
        **kwargs,
    )


# ── Fixtures locales ─────────────────────────────────────────────────────────

@pytest.fixture
def profile_paper(risk_profile_paper):
    """Alias pour lisibilité."""
    return risk_profile_paper


@pytest.fixture
def profile_live(risk_profile_live):
    return risk_profile_live


# ─────────────────────────────────────────────────────────────────────────────
#  SOFT — franchissables avec override=True
# ─────────────────────────────────────────────────────────────────────────────

class TestSoftOverride:

    @pytest.mark.django_db
    def test_ai_confidence_soft_blocks_without_override(self, portfolio_paper, profile_paper):
        """AI_CONFIDENCE_TOO_LOW bloque quand override=False."""
        profile_paper.min_confidence = Decimal("0.90")
        profile_paper.save()

        result = _validate(portfolio_paper, override=False, confidence=Decimal("0.50"))

        assert result.decision == "BLOCK"
        assert result.block_code == "AI_CONFIDENCE_TOO_LOW"
        assert result.block_severity == "SOFT"

    @pytest.mark.django_db
    def test_ai_confidence_passes_with_override(self, portfolio_paper, profile_paper):
        """AI_CONFIDENCE_TOO_LOW est franchi avec override=True."""
        profile_paper.min_confidence = Decimal("0.90")
        profile_paper.save()

        result = _validate(portfolio_paper, override=True, confidence=Decimal("0.50"))

        assert result.decision == "APPROVE"
        assert result.block_code == ""
        # L'override est tracé dans le payload
        assert "risk_override" in result.payload
        applied = result.payload["risk_override"].get("applied_to", [])
        assert any(e["code"] == "AI_CONFIDENCE_TOO_LOW" for e in applied)

    @pytest.mark.django_db
    def test_stop_loss_required_soft_blocks(self, portfolio_paper, profile_paper):
        """STOP_LOSS_REQUIRED bloque quand override=False (non-Deriv)."""
        profile_paper.require_stop_loss = True
        profile_paper.save()

        # Forcer un symbole non-Deriv pour déclencher la règle stop-loss
        result = RiskGuardService.validate_trade(
            portfolio=portfolio_paper,
            symbol="EURUSD",           # pas un symbole Deriv volatility
            side="BUY",
            requested_stake=Decimal("10.00"),
            approved_quantity=Decimal("1"),
            approved_notional=Decimal("10.00"),
            entry_price=Decimal("1.10"),
            stop_loss=None,            # absent exprès
            take_profit=Decimal("1.15"),
            confidence=Decimal("0.95"),
            risk_override=False,
        )

        assert result.decision == "BLOCK"
        assert result.block_code == "STOP_LOSS_REQUIRED"
        assert result.block_severity == "SOFT"

    @pytest.mark.django_db
    def test_stop_loss_required_passes_with_override(self, portfolio_paper, profile_paper):
        """STOP_LOSS_REQUIRED est franchi avec override=True."""
        profile_paper.require_stop_loss = True
        profile_paper.save()

        result = RiskGuardService.validate_trade(
            portfolio=portfolio_paper,
            symbol="EURUSD",
            side="BUY",
            requested_stake=Decimal("10.00"),
            approved_quantity=Decimal("1"),
            approved_notional=Decimal("10.00"),
            entry_price=Decimal("1.10"),
            stop_loss=None,
            take_profit=Decimal("1.15"),
            confidence=Decimal("0.95"),
            risk_override=True,
            risk_override_reason="test stop override",
            risk_override_user_id=1,
        )

        assert result.decision == "APPROVE"
        applied = result.payload["risk_override"].get("applied_to", [])
        assert any(e["code"] == "STOP_LOSS_REQUIRED" for e in applied)

    @pytest.mark.django_db
    def test_max_open_positions_soft_blocks_live(self, portfolio_live, profile_live):
        """MAX_OPEN_POSITIONS bloque en LIVE quand override=False."""
        profile_live.max_open_positions = 1
        profile_live.save()

        # Patcher open_positions_count pour simuler la saturation
        with mock.patch.object(
            RiskGuardService, "open_positions_count", return_value=1
        ):
            result = _validate(portfolio_live, override=False)

        assert result.decision == "BLOCK"
        assert result.block_code == "MAX_OPEN_POSITIONS"
        assert result.block_severity == "SOFT"

    @pytest.mark.django_db
    def test_max_open_positions_passes_with_override(self, portfolio_live, profile_live):
        """MAX_OPEN_POSITIONS est franchi avec override=True."""
        profile_live.max_open_positions = 1
        profile_live.save()

        with mock.patch.object(
            RiskGuardService, "open_positions_count", return_value=1
        ):
            result = _validate(portfolio_live, override=True)

        assert result.decision == "APPROVE"
        applied = result.payload["risk_override"].get("applied_to", [])
        assert any(e["code"] == "MAX_OPEN_POSITIONS" for e in applied)

    @pytest.mark.django_db
    def test_daily_loss_limit_soft_blocks(self, portfolio_paper, profile_paper):
        """DAILY_LOSS_LIMIT bloque quand override=False."""
        profile_paper.max_daily_loss = Decimal("1.00")
        profile_paper.kill_switch_enabled = False  # on teste juste le soft block
        profile_paper.save()

        # Injecter un état journalier avec une perte dépassée
        from risk.models import DailyRiskState
        DailyRiskState.objects.update_or_create(
            portfolio=portfolio_paper,
            day=timezone.localdate(),
            defaults={
                "total_loss_percent": Decimal("5.00"),
                "total_loss_amount": Decimal("500.00"),
                "equity_open": Decimal("10000.00"),
                "equity_current": Decimal("9500.00"),
            },
        )

        result = _validate(portfolio_paper, override=False)

        assert result.decision == "BLOCK"
        assert result.block_code == "DAILY_LOSS_LIMIT"
        assert result.block_severity == "SOFT"

    @pytest.mark.django_db
    def test_daily_loss_limit_passes_with_override(self, portfolio_paper, profile_paper):
        """DAILY_LOSS_LIMIT est franchi avec override=True."""
        profile_paper.max_daily_loss = Decimal("1.00")
        profile_paper.kill_switch_enabled = False
        profile_paper.save()

        from risk.models import DailyRiskState
        DailyRiskState.objects.update_or_create(
            portfolio=portfolio_paper,
            day=timezone.localdate(),
            defaults={
                "total_loss_percent": Decimal("5.00"),
                "total_loss_amount": Decimal("500.00"),
                "equity_open": Decimal("10000.00"),
                "equity_current": Decimal("9500.00"),
            },
        )

        result = _validate(portfolio_paper, override=True)

        assert result.decision == "APPROVE"
        applied = result.payload["risk_override"].get("applied_to", [])
        assert any(e["code"] == "DAILY_LOSS_LIMIT" for e in applied)

    @pytest.mark.django_db
    def test_weekly_loss_limit_soft_blocks_live(self, portfolio_live, profile_live):
        """WEEKLY_LOSS_LIMIT bloque en LIVE quand override=False."""
        profile_live.max_weekly_loss = Decimal("1.00")
        profile_live.kill_switch_enabled = False
        profile_live.save()

        from risk.models import WeeklyRiskState
        from datetime import date, timedelta
        week_start = date.today() - timedelta(days=date.today().weekday())
        WeeklyRiskState.objects.update_or_create(
            portfolio=portfolio_live,
            week_start=week_start,
            defaults={
                "total_loss_percent": Decimal("5.00"),
                "total_loss_amount": Decimal("500.00"),
                "equity_open": Decimal("10000.00"),
                "equity_current": Decimal("9500.00"),
            },
        )

        result = _validate(portfolio_live, override=False)

        assert result.decision == "BLOCK"
        assert result.block_code == "WEEKLY_LOSS_LIMIT"
        assert result.block_severity == "SOFT"

    @pytest.mark.django_db
    def test_weekly_loss_limit_passes_with_override(self, portfolio_live, profile_live):
        """WEEKLY_LOSS_LIMIT est franchi avec override=True."""
        profile_live.max_weekly_loss = Decimal("1.00")
        profile_live.kill_switch_enabled = False
        profile_live.save()

        from risk.models import WeeklyRiskState
        from datetime import date, timedelta
        week_start = date.today() - timedelta(days=date.today().weekday())
        WeeklyRiskState.objects.update_or_create(
            portfolio=portfolio_live,
            week_start=week_start,
            defaults={
                "total_loss_percent": Decimal("5.00"),
                "total_loss_amount": Decimal("500.00"),
                "equity_open": Decimal("10000.00"),
                "equity_current": Decimal("9500.00"),
            },
        )

        result = _validate(portfolio_live, override=True)

        assert result.decision == "APPROVE"
        applied = result.payload["risk_override"].get("applied_to", [])
        assert any(e["code"] == "WEEKLY_LOSS_LIMIT" for e in applied)


# ─────────────────────────────────────────────────────────────────────────────
#  HARD — ne doivent JAMAIS être franchis, même avec override=True
# ─────────────────────────────────────────────────────────────────────────────

class TestHardBlock:

    @pytest.mark.django_db
    def test_kill_switch_live_hard_blocks_even_with_override(
        self, portfolio_live, profile_live
    ):
        """KILL_SWITCH_LIVE est HARD : override=True ne change rien en LIVE."""
        KillSwitchEvent.objects.create(
            portfolio=portfolio_live,
            reason_code="DAILY_LOSS_LIMIT",
            reason="Perte journalière atteinte.",
            is_active=True,
            triggered_at=timezone.now(),
        )

        # Sans override
        result_no = _validate(portfolio_live, override=False)
        assert result_no.decision == "BLOCK"
        assert result_no.block_code == "KILL_SWITCH_LIVE"
        assert result_no.block_severity == "HARD"

        # Avec override → toujours BLOCK
        result_with = _validate(portfolio_live, override=True)
        assert result_with.decision == "BLOCK"
        assert result_with.block_code == "KILL_SWITCH_LIVE"
        assert result_with.block_severity == "HARD"

    @pytest.mark.django_db
    def test_live_trading_forbidden_hard_blocks(self, portfolio_live, profile_live):
        """LIVE_TRADING_FORBIDDEN est HARD même avec override=True."""
        profile_live.allow_live_trading = False
        profile_live.save()

        result = _validate(portfolio_live, override=True)

        assert result.decision == "BLOCK"
        assert result.block_code == "LIVE_TRADING_FORBIDDEN"
        assert result.block_severity == "HARD"

    @pytest.mark.django_db
    def test_short_forbidden_hard_blocks(self, portfolio_paper, profile_paper):
        """SHORT_FORBIDDEN est HARD même avec override=True."""
        profile_paper.allow_short = False
        profile_paper.save()

        result = RiskGuardService.validate_trade(
            portfolio=portfolio_paper,
            symbol="R_100",
            side="SELL",                # short
            requested_stake=Decimal("10.00"),
            approved_quantity=Decimal("1"),
            approved_notional=Decimal("10.00"),
            entry_price=Decimal("100.00"),
            stop_loss=None,
            take_profit=Decimal("90.00"),
            confidence=Decimal("0.95"),
            risk_override=True,         # override tenté
            risk_override_reason="force short",
            risk_override_user_id=1,
        )

        assert result.decision == "REJECT"
        assert result.block_code == "SHORT_FORBIDDEN"
        assert result.block_severity == "HARD"

    @pytest.mark.django_db
    def test_hard_codes_set_is_superset_of_constants(self):
        """Vérification que HARD_BLOCK_CODES contient bien les trois codes attendus."""
        expected = {"KILL_SWITCH_LIVE", "LIVE_TRADING_FORBIDDEN", "SHORT_FORBIDDEN"}
        assert expected.issubset(RiskGuardService.HARD_BLOCK_CODES)


# ─────────────────────────────────────────────────────────────────────────────
#  Payload d'audit
# ─────────────────────────────────────────────────────────────────────────────

class TestOverrideAuditPayload:

    @pytest.mark.django_db
    def test_override_payload_always_present_when_flag_true(
        self, portfolio_paper, profile_paper
    ):
        """Quand risk_override=True, la clé 'risk_override' est toujours dans le payload,
        même si aucun blocage SOFT n'a été rencontré (trade propre)."""
        result = RiskGuardService.validate_trade(
            portfolio=portfolio_paper,
            symbol="R_100",
            side="BUY",
            requested_stake=Decimal("10.00"),
            approved_quantity=Decimal("1"),
            approved_notional=Decimal("10.00"),
            entry_price=Decimal("100.00"),
            stop_loss=None,
            take_profit=Decimal("110.00"),
            confidence=Decimal("0.95"),
            risk_override=True,
            risk_override_reason="audit test",
            risk_override_user_id=42,
        )

        assert "risk_override" in result.payload
        ro = result.payload["risk_override"]
        assert ro["user_id"] == 42
        assert ro["reason"] == "audit test"
        assert isinstance(ro["applied_to"], list)

    @pytest.mark.django_db
    def test_override_payload_absent_when_flag_false(
        self, portfolio_paper, profile_paper
    ):
        """Quand risk_override=False, 'risk_override' est absent du payload."""
        result = _validate(portfolio_paper, override=False)
        assert "risk_override" not in result.payload
