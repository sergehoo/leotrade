from __future__ import annotations

from decimal import Decimal
from django.utils import timezone

from strategies.models import Strategy
from portfolio.models import Portfolio
from wallet.models import Wallet


class StrategyRiskGuard:
    @staticmethod
    def can_emit_signal(strategy: Strategy) -> tuple[bool, str]:
        if not strategy.is_active:
            return False, "Stratégie inactive."
        if strategy.status in ["PAUSED", "ARCHIVED", "FAILED"]:
            return False, f"Stratégie en statut {strategy.status}."
        return True, ""

    @staticmethod
    def passes_confidence_threshold(strategy: Strategy, confidence: float) -> tuple[bool, str]:
        if confidence < (strategy.min_confidence_threshold or 0.0):
            return False, "Confiance insuffisante."
        return True, ""

    @staticmethod
    def daily_signal_limit_ok(strategy: Strategy) -> tuple[bool, str]:
        today = timezone.now().date()
        count = strategy.signals.filter(created_at__date=today).count()
        if strategy.max_signals_per_day and count >= strategy.max_signals_per_day:
            return False, "Limite quotidienne de signaux atteinte."
        return True, ""

    @staticmethod
    def portfolio_risk_ok(strategy: Strategy, portfolio: Portfolio | None) -> tuple[bool, str]:
        if not portfolio:
            return True, ""

        if strategy.max_daily_drawdown_percent and portfolio.current_drawdown_percent >= strategy.max_daily_drawdown_percent:
            return False, "Drawdown quotidien maximal dépassé."

        if strategy.max_total_exposure_percent and portfolio.equity > 0:
            exposure = sum((p.exposure_value or Decimal("0")) for p in portfolio.positions.filter(status="OPEN"))
            exposure_pct = float((exposure / portfolio.equity) * 100) if portfolio.equity else 0.0
            if exposure_pct >= strategy.max_total_exposure_percent:
                return False, "Exposition maximale dépassée."

        return True, ""

    @staticmethod
    def wallet_risk_ok(strategy: Strategy, wallet: Wallet | None) -> tuple[bool, str]:
        if not wallet:
            return True, ""
        if not wallet.is_active:
            return False, "Wallet inactif."
        if wallet.available_balance <= 0:
            return False, "Aucun solde disponible."
        return True, ""