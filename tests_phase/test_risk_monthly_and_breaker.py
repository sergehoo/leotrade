"""
Phase risque avancé — MonthlyRiskState + StrategyCircuitBreaker.

Couverture :
  1. refresh_monthly_state crée/rafraîchit l'état mensuel.
  2. MONTHLY_LOSS_LIMIT bloque (SOFT) en LIVE quand la perte du mois
     dépasse max_monthly_loss, et se franchit avec override.
  3. StrategyCircuitBreakerService coupe une stratégie dégradée
     (expectancy négative) et reste idempotent ; resolve() réactive.
  4. Une stratégie saine ou sans échantillon suffisant n'est pas coupée.
"""

from decimal import Decimal

import pytest
from django.utils import timezone

from risk.models import MonthlyRiskState, StrategyCircuitBreakerEvent
from risk.services import RiskGuardService, RiskStateService
from risk.services_circuit_breaker import StrategyCircuitBreakerService

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
)


# ─────────────────────────────────────────────────────────────────────────────
#  1. MonthlyRiskState
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_refresh_monthly_state_creates_state(portfolio_paper):
    state = RiskStateService.refresh_monthly_state(portfolio_paper)
    assert isinstance(state, MonthlyRiskState)
    assert state.month_start == timezone.localdate().replace(day=1)
    assert state.equity_current > 0


@pytest.mark.django_db
def test_refresh_monthly_state_idempotent(portfolio_paper):
    s1 = RiskStateService.refresh_monthly_state(portfolio_paper)
    s2 = RiskStateService.refresh_monthly_state(portfolio_paper)
    assert s1.pk == s2.pk
    assert MonthlyRiskState.objects.filter(portfolio=portfolio_paper).count() == 1


@pytest.mark.django_db
def test_monthly_loss_limit_soft_blocks_live(portfolio_live, risk_profile_live):
    """MONTHLY_LOSS_LIMIT bloque en LIVE quand override=False."""
    risk_profile_live.max_monthly_loss = Decimal("1.00")
    risk_profile_live.kill_switch_enabled = False
    risk_profile_live.save()

    month_start = timezone.localdate().replace(day=1)
    MonthlyRiskState.objects.update_or_create(
        portfolio=portfolio_live,
        month_start=month_start,
        defaults={
            # refresh recalcule la perte depuis l'équité réelle (10 000) :
            # equity_open au-dessus simule ~4,76 % de perte mensuelle.
            "equity_open": Decimal("10500.00"),
            "equity_current": Decimal("10000.00"),
        },
    )

    result = RiskGuardService.validate_trade(
        portfolio=portfolio_live, risk_override=False, **TRADE_KWARGS
    )

    assert result.decision == "BLOCK"
    assert result.block_code == "MONTHLY_LOSS_LIMIT"
    assert result.block_severity == "SOFT"


@pytest.mark.django_db
def test_monthly_loss_limit_passes_with_override(portfolio_live, risk_profile_live, user):
    risk_profile_live.max_monthly_loss = Decimal("1.00")
    risk_profile_live.kill_switch_enabled = False
    risk_profile_live.save()

    month_start = timezone.localdate().replace(day=1)
    MonthlyRiskState.objects.update_or_create(
        portfolio=portfolio_live,
        month_start=month_start,
        defaults={
            "equity_open": Decimal("10500.00"),
            "equity_current": Decimal("10000.00"),
        },
    )

    result = RiskGuardService.validate_trade(
        portfolio=portfolio_live,
        risk_override=True,
        risk_override_reason="test monthly override",
        risk_override_user_id=user.id,
        **TRADE_KWARGS,
    )

    assert result.decision == "APPROVE"
    applied = result.payload["risk_override"].get("applied_to", [])
    assert any(e["code"] == "MONTHLY_LOSS_LIMIT" for e in applied)


# ─────────────────────────────────────────────────────────────────────────────
#  2. Circuit breaker stratégie
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def strategy(db, user):
    from market.models import Asset, Timeframe
    from strategies.models import Strategy

    asset = Asset.objects.create(
        symbol="R_100", name="Volatility 100", asset_class="SYNTHETIC",
        exchange="DERIV", is_active=True,
    )
    timeframe, _ = Timeframe.objects.get_or_create(
        code="M5", defaults={"minutes": 5},
    )
    return Strategy.objects.create(
        name="CB Test Strategy",
        asset=asset,
        timeframe=timeframe,
        strategy_type="RULE",
        status="PAPER",
        is_active=True,
    )


def _snapshot(strategy, *, win_rate, expectancy, total_trades):
    from trading.models_hedge_fund import LearningSnapshot
    return LearningSnapshot.objects.create(
        strategy=strategy,
        win_rate=win_rate,
        expectancy=expectancy,
        total_trades=total_trades,
    )


@pytest.mark.django_db
def test_breaker_trips_on_negative_expectancy(strategy):
    _snapshot(strategy, win_rate=0.50, expectancy=-0.8, total_trades=25)

    event = StrategyCircuitBreakerService.evaluate_strategy(strategy)

    assert event is not None
    assert event.reason_code == "NEGATIVE_EXPECTANCY"
    strategy.refresh_from_db()
    assert strategy.is_active is False
    assert strategy.status == "PAUSED"


@pytest.mark.django_db
def test_breaker_trips_on_degraded_win_rate(strategy):
    _snapshot(strategy, win_rate=0.20, expectancy=-1.5, total_trades=40)

    event = StrategyCircuitBreakerService.evaluate_strategy(strategy)

    assert event is not None
    assert event.reason_code == "DEGRADED_WIN_RATE"
    assert event.total_trades == 40


@pytest.mark.django_db
def test_breaker_skips_healthy_strategy(strategy):
    _snapshot(strategy, win_rate=0.62, expectancy=0.4, total_trades=50)

    assert StrategyCircuitBreakerService.evaluate_strategy(strategy) is None
    strategy.refresh_from_db()
    assert strategy.is_active is True


@pytest.mark.django_db
def test_breaker_skips_insufficient_sample(strategy):
    _snapshot(strategy, win_rate=0.0, expectancy=-5.0, total_trades=3)

    assert StrategyCircuitBreakerService.evaluate_strategy(strategy) is None
    strategy.refresh_from_db()
    assert strategy.is_active is True


@pytest.mark.django_db
def test_breaker_idempotent(strategy):
    _snapshot(strategy, win_rate=0.10, expectancy=-2.0, total_trades=30)

    first = StrategyCircuitBreakerService.evaluate_strategy(strategy)
    assert first is not None

    # Une stratégie coupée (inactive) n'est pas re-coupée
    strategy.refresh_from_db()
    assert StrategyCircuitBreakerService.evaluate_strategy(strategy) is None
    assert StrategyCircuitBreakerEvent.objects.filter(strategy=strategy).count() == 1


@pytest.mark.django_db
def test_breaker_resolve_reactivates(strategy, user):
    _snapshot(strategy, win_rate=0.10, expectancy=-2.0, total_trades=30)
    StrategyCircuitBreakerService.evaluate_strategy(strategy)
    strategy.refresh_from_db()
    assert strategy.is_active is False

    resolved = StrategyCircuitBreakerService.resolve(
        strategy, user=user, reactivate=True
    )

    assert resolved == 1
    strategy.refresh_from_db()
    assert strategy.is_active is True
    event = StrategyCircuitBreakerEvent.objects.get(strategy=strategy)
    assert event.is_active is False
    assert event.resolved_by == user


@pytest.mark.django_db
def test_evaluate_all_only_trips_degraded(strategy, user):
    from market.models import Asset, Timeframe
    from strategies.models import Strategy

    asset2 = Asset.objects.create(
        symbol="R_50", name="Volatility 50", asset_class="SYNTHETIC",
        exchange="DERIV", is_active=True,
    )
    timeframe = Timeframe.objects.get(code="M5")
    healthy = Strategy.objects.create(
        name="Healthy Strategy", asset=asset2, timeframe=timeframe,
        strategy_type="RULE", status="PAPER", is_active=True,
    )

    _snapshot(strategy, win_rate=0.15, expectancy=-1.0, total_trades=20)
    _snapshot(healthy, win_rate=0.65, expectancy=0.5, total_trades=20)

    tripped = StrategyCircuitBreakerService.evaluate_all()

    assert [e.strategy_id for e in tripped] == [strategy.id]
    healthy.refresh_from_db()
    assert healthy.is_active is True
