from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


@dataclass
class BrokerBalanceDTO:
    currency: str
    total: Decimal
    available: Decimal
    locked: Decimal = Decimal("0")


@dataclass
class BrokerPositionDTO:
    symbol: str
    side: str
    quantity: Decimal
    entry_price: Decimal
    current_price: Decimal
    average_entry_price: Decimal
    leverage: Decimal = Decimal("1")
    margin_used: Decimal = Decimal("0")
    broker_position_id: Optional[str] = None
    cost_basis_status: str = "KNOWN"
    metadata: dict = field(default_factory=dict)


@dataclass
class BrokerFillDTO:
    broker_fill_id: Optional[str]
    quantity: Decimal
    price: Decimal
    notional: Decimal
    fee: Decimal
    fee_currency: str
    fill_time:datetime
    liquidity_type: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class BrokerOrderResultDTO:
    broker_order_id: Optional[str]
    broker_client_order_id: Optional[str]
    status: str
    submitted_at:datetime
    fills: list
    raw: dict = field(default_factory=dict)


@dataclass
class BrokerConstraintDTO:
    symbol: str
    min_qty: Decimal
    max_qty: Decimal
    qty_step: Decimal
    min_notional: Decimal
    price_tick: Decimal
    leverage_min: Decimal = Decimal("1")
    leverage_max: Decimal = Decimal("1")
    contract_size: Decimal = Decimal("1")
    raw_payload: dict = field(default_factory=dict)