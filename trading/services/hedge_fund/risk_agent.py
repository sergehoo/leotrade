from __future__ import annotations

from decimal import Decimal
from django.utils import timezone

from portfolio.models import Position
from trading.models_hedge_fund import RiskState, RiskPolicy


class GlobalRiskAgent:
    @classmethod
    def evaluate(cls, portfolio):
        policy, _ = RiskPolicy.objects.get_or_create(portfolio=portfolio)

        positions = Position.objects.filter(portfolio=portfolio, status="OPEN")
        open_count = positions.count()
        total_open_pnl = sum([p.pnl or Decimal("0") for p in positions], Decimal("0"))

        balance = float(portfolio.current_balance or 0)
        equity = float(portfolio.equity or portfolio.current_balance or 0)

        drawdown_percent = 0.0
        if balance > 0 and equity < balance:
            drawdown_percent = ((balance - equity) / balance) * 100

        exposure_percent = 0.0
        if balance > 0:
            exposure_nominal = sum([float((p.entry_price or 0) * (p.quantity or 0)) for p in positions])
            exposure_percent = (exposure_nominal / balance) * 100

        correlation_risk_score = min(1.0, open_count / max(policy.max_correlated_positions, 1))

        status = "NORMAL"
        allow_new_positions = True
        recommended_risk_percent = policy.base_risk_per_trade_percent
        reason = "Risque sous contrôle."

        if drawdown_percent >= policy.max_drawdown_percent:
            status = "BLOCK"
            allow_new_positions = False
            recommended_risk_percent = policy.min_risk_per_trade_percent
            reason = "Drawdown maximal atteint."
        elif open_count >= policy.max_open_positions:
            status = "BLOCK"
            allow_new_positions = False
            recommended_risk_percent = policy.min_risk_per_trade_percent
            reason = "Nombre maximal de positions ouvertes atteint."
        elif drawdown_percent >= (policy.max_drawdown_percent * 0.7):
            status = "REDUCE"
            allow_new_positions = True
            recommended_risk_percent = max(policy.min_risk_per_trade_percent, policy.base_risk_per_trade_percent * 0.5)
            reason = "Drawdown élevé, réduction du risque par trade."
        elif exposure_percent >= 80:
            status = "CAUTION"
            recommended_risk_percent = max(policy.min_risk_per_trade_percent, policy.base_risk_per_trade_percent * 0.7)
            reason = "Exposition portefeuille élevée."

        return RiskState.objects.create(
            portfolio=portfolio,
            status=status,
            current_daily_pnl=Decimal("0.00"),
            current_weekly_pnl=Decimal("0.00"),
            current_drawdown_percent=round(drawdown_percent, 4),
            exposure_percent=round(exposure_percent, 4),
            correlation_risk_score=round(correlation_risk_score, 4),
            recommended_risk_percent=round(recommended_risk_percent, 4),
            allow_new_positions=allow_new_positions,
            reason=reason,
            payload={
                "open_positions": open_count,
                "total_open_pnl": float(total_open_pnl),
            },
        )