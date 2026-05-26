# /Users/ogahserge/Documents/leoTrade/trading/services/agents/portfolio_advisor_agent.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from django.db import transaction

from portfolio.models import Portfolio
from trading.models import AgentRun, PortfolioAdvice


@dataclass
class PortfolioAdviceResult:
    action: str
    recommended_risk_percent: float = 1.0
    reason: str = ""
    risk_score: float = 0.0
    max_new_positions: int = 1
    data: Dict[str, Any] = field(default_factory=dict)
    advice_record: Optional[PortfolioAdvice] = None

    def __str__(self) -> str:
        return f"{self.action} | risk={self.risk_score:.2f} | {self.reason or 'No reason'}"


class PortfolioAdvisorAgent:
    MAX_OPEN_POSITIONS = 25
    BLOCK_DRAWDOWN_PERCENT = 20.0
    REDUCE_DRAWDOWN_PERCENT = 10.0
    HIGH_EXPOSURE_PERCENT = 80.0
    CLOSE_WEAK_POSITIONS_DRAWDOWN_PERCENT = 30.0

    @classmethod
    @transaction.atomic
    def advise(cls, portfolio: Portfolio, persist: bool = True) -> PortfolioAdviceResult:
        open_positions_count = portfolio.positions.filter(status="OPEN").count()

        current_balance = cls._to_float(getattr(portfolio, "current_balance", None)) or 0.0
        equity = cls._to_float(getattr(portfolio, "equity", None))
        starting_balance = cls._to_float(getattr(portfolio, "starting_balance", None))

        if equity is None:
            equity = current_balance

        if starting_balance is None:
            starting_balance = current_balance

        base_data = {
            "open_positions": open_positions_count,
            "current_balance": current_balance,
            "equity": equity,
            "starting_balance": starting_balance,
            "drawdown_percent": None,
            "exposure_percent": None,
        }

        if starting_balance <= 0:
            result = PortfolioAdviceResult(
                action="BLOCK_NEW_POSITIONS",
                recommended_risk_percent=0.0,
                reason="Capital initial invalide ou nul.",
                risk_score=1.0,
                max_new_positions=0,
                data=base_data,
            )
            return cls._persist_result(portfolio, result) if persist else result

        peak_balance = cls._to_float(getattr(portfolio, "peak_equity", None))
        if peak_balance is None or peak_balance <= 0:
            peak_balance = max(starting_balance, equity, current_balance)

        drawdown_percent = 0.0
        if peak_balance > 0:
            drawdown_percent = max(0.0, ((peak_balance - equity) / peak_balance) * 100)

        exposure_percent = 0.0
        if cls.MAX_OPEN_POSITIONS > 0:
            exposure_percent = (open_positions_count / cls.MAX_OPEN_POSITIONS) * 100

        portfolio_mode = str(getattr(portfolio, "mode", "") or "").upper()
        broker_mode = str(getattr(getattr(portfolio, "broker_account", None), "mode", "") or "").upper()
        is_paper = portfolio_mode in ("PAPER", "DEMO") or broker_mode in ("PAPER", "DEMO")

        data = {
            "open_positions": open_positions_count,
            "current_balance": current_balance,
            "equity": equity,
            "starting_balance": starting_balance,
            "peak_balance": peak_balance,
            "drawdown_percent": drawdown_percent,
            "exposure_percent": exposure_percent,
            "portfolio_mode": portfolio_mode,
            "broker_mode": broker_mode,
            "is_paper": is_paper,
        }

        # Bypass PAPER/DEMO AVANT les blocages critiques
        if is_paper and drawdown_percent >= cls.BLOCK_DRAWDOWN_PERCENT:
            result = PortfolioAdviceResult(
                action="REDUCE_RISK",
                recommended_risk_percent=0.25,
                reason=f"Drawdown critique ({drawdown_percent:.2f}%) détecté, mais exécution autorisée en mode PAPER/DEMO.",
                risk_score=0.75,
                max_new_positions=1,
                data={**data, "paper_bypass": True},
            )
            return cls._persist_result(portfolio, result) if persist else result

        if drawdown_percent >= cls.CLOSE_WEAK_POSITIONS_DRAWDOWN_PERCENT:
            result = PortfolioAdviceResult(
                action="CLOSE_WEAK_POSITIONS",
                recommended_risk_percent=0.0,
                reason=f"Drawdown très critique ({drawdown_percent:.2f}%). Réduction agressive recommandée.",
                risk_score=0.99,
                max_new_positions=0,
                data=data,
            )
            return cls._persist_result(portfolio, result) if persist else result

        if open_positions_count >= cls.MAX_OPEN_POSITIONS:
            result = PortfolioAdviceResult(
                action="BLOCK_NEW_POSITIONS",
                recommended_risk_percent=0.0,
                reason="Nombre maximum de positions ouvertes atteint.",
                risk_score=0.95,
                max_new_positions=0,
                data=data,
            )
            return cls._persist_result(portfolio, result) if persist else result

        if drawdown_percent >= cls.BLOCK_DRAWDOWN_PERCENT:
            result = PortfolioAdviceResult(
                action="BLOCK_NEW_POSITIONS",
                recommended_risk_percent=0.0,
                reason=f"Drawdown critique ({drawdown_percent:.2f}%).",
                risk_score=0.95,
                max_new_positions=0,
                data=data,
            )
            return cls._persist_result(portfolio, result) if persist else result

        if drawdown_percent >= cls.REDUCE_DRAWDOWN_PERCENT or exposure_percent >= cls.HIGH_EXPOSURE_PERCENT:
            result = PortfolioAdviceResult(
                action="REDUCE_RISK",
                recommended_risk_percent=0.5,
                reason=f"Risque modéré détecté (drawdown={drawdown_percent:.2f}%, exposition={exposure_percent:.2f}%).",
                risk_score=0.60,
                max_new_positions=max(1, cls.MAX_OPEN_POSITIONS - open_positions_count),
                data=data,
            )
            return cls._persist_result(portfolio, result) if persist else result

        result = PortfolioAdviceResult(
            action="ALLOW_NEW_POSITIONS",
            recommended_risk_percent=1.0,
            reason="Portefeuille dans les limites de risque autorisées.",
            risk_score=0.20,
            max_new_positions=max(1, cls.MAX_OPEN_POSITIONS - open_positions_count),
            data=data,
        )
        return cls._persist_result(portfolio, result) if persist else result

    @classmethod
    def _persist_result(cls, portfolio: Portfolio, result: PortfolioAdviceResult) -> PortfolioAdviceResult:
        agent_run = AgentRun.objects.create(
            agent_type="PORTFOLIO_ADVISOR",
            status="SUCCEEDED",
            user=getattr(portfolio, "user", None),
            input_payload={
                "portfolio_id": portfolio.id,
                "portfolio_name": getattr(portfolio, "name", ""),
            },
            output_payload={
                "action": result.action,
                "reason": result.reason,
                "risk_score": result.risk_score,
                "recommended_risk_percent": result.recommended_risk_percent,
                "max_new_positions": result.max_new_positions,
                "data": result.data,
            },
        )

        advice_record = PortfolioAdvice.objects.create(
            portfolio=portfolio,
            agent_run=agent_run,
            action=result.action,
            confidence=max(0.0, min(1.0, 1.0 - result.risk_score)),
            max_new_positions=result.max_new_positions,
            recommended_risk_percent=result.recommended_risk_percent,
            summary=result.reason,
            payload=result.data,
        )

        result.advice_record = advice_record
        return result

    @staticmethod
    def _to_float(value) -> Optional[float]:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None