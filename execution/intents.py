"""
execution/intents.py
====================

OrderIntent : structure immuable qui représente l'INTENTION de passer un ordre,
AVANT validation par le RiskEngine et création de l'Order DB.

C'est la *seule* interface acceptée par ExecutionOrchestrator.submit().
Aucun caller ne doit créer un execution.models.Order directement.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class OrderIntent:
    """
    Champs minimaux pour soumettre un ordre.
    """

    user_id: int
    portfolio_id: int
    broker_account_id: int
    symbol: str
    side: str                       # "BUY" / "SELL"
    order_type: str = "MARKET"      # "MARKET" / "LIMIT" / "STOP" / "STOP_LIMIT"

    requested_quantity: Decimal | None = None
    requested_stake_amount: Decimal | None = None  # alternative pour Deriv (stake en cash)

    requested_price: Decimal | None = None         # pour LIMIT
    stop_price: Decimal | None = None              # pour STOP

    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    leverage: Decimal = Decimal("1")

    mode: str = "PAPER"             # "PAPER" / "LIVE"
    source: str = "MANUAL"          # "MANUAL" / "STRATEGY" / "AI_ASSISTED"

    asset_id: int | None = None
    signal_id: int | None = None
    trade_idea_id: int | None = None

    idempotency_key: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.side not in ("BUY", "SELL"):
            raise ValueError(f"side invalide: {self.side}")
        if self.order_type not in ("MARKET", "LIMIT", "STOP", "STOP_LIMIT"):
            raise ValueError(f"order_type invalide: {self.order_type}")
        if self.mode not in ("PAPER", "LIVE"):
            raise ValueError(f"mode invalide: {self.mode}")
        if self.requested_quantity is None and self.requested_stake_amount is None:
            raise ValueError("requested_quantity OU requested_stake_amount obligatoire")
