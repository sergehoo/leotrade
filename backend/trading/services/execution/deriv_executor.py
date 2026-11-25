from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from trading.services.execution.canonical_signal import CanonicalSignalExecutionService


@dataclass
class PortfolioAdvice:
    action: str
    recommended_risk_percent: float = 1.0
    reason: str = ""
    risk_score: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.action} | risk={self.risk_score:.2f} | {self.reason or 'No reason'}"


class DerivExecutorError(Exception):
    pass


class DerivExecutor:
    """Deprecated compatibility facade delegating to the canonical OMS."""

    def __init__(self, broker_account, portfolio):
        self.broker_account = broker_account
        self.portfolio = portfolio

    def execute_signal(self, signal, approved_quantity: Decimal):
        if self.broker_account.broker != "DERIV":
            raise DerivExecutorError("Ce service de compatibilité exige un broker Deriv.")

        try:
            order = CanonicalSignalExecutionService(
                self.broker_account,
                self.portfolio,
            ).execute(
                signal=signal,
                approved_quantity=approved_quantity,
            )
        except Exception as exc:
            raise DerivExecutorError(str(exc)) from exc

        contract = SimpleNamespace(
            contract_id=order.broker_order_id,
            status=order.status,
            order_id=order.id,
        )
        position = self.portfolio.positions.filter(
            metadata__origin_order_id=order.id,
        ).first()
        return {"order": order, "contract": contract, "position": position}
