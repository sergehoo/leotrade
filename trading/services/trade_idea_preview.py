from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_CEILING

from brokers.models import BrokerConstraint
from brokers.services.base import BrokerConstraintSyncService


class TradeIdeaPreviewService:
    DEFAULT_MIN_QTY = Decimal("0.00000001")
    DEFAULT_QTY_STEP = Decimal("0.00000001")
    DEFAULT_MIN_NOTIONAL = Decimal("0")
    ZERO = Decimal("0")
    MONEY_PRECISION = Decimal("0.01")

    DERIV_DEFAULT_MIN_STAKE = Decimal("1.00")

    DERIV_SYNTHETIC_PREFIXES = (
        "R_",
        "1HZ",
        "HZ",
        "JD",
        "JUMP",
        "CRASH",
        "BOOM",
        "STEP",
        "VOL",
    )

    @staticmethod
    def _d(value, default="0") -> Decimal:
        try:
            if value is None or value == "":
                return Decimal(default)
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal(default)

    @classmethod
    def _money_up(cls, value: Decimal) -> Decimal:
        try:
            return value.quantize(cls.MONEY_PRECISION, rounding=ROUND_CEILING)
        except Exception:
            return cls.ZERO

    @classmethod
    def _is_deriv_synthetic_symbol(cls, symbol: str) -> bool:
        symbol = str(symbol or "").upper().strip()
        return symbol.startswith(cls.DERIV_SYNTHETIC_PREFIXES)

    @classmethod
    def _is_deriv_broker(cls, broker_account) -> bool:
        broker = str(getattr(broker_account, "broker", "") or "").upper()
        return broker == "DERIV"

    @classmethod
    def _estimate_deriv_minimum_stake(cls, *, idea, broker_account) -> dict:
        symbol = str(getattr(idea, "symbol", "") or "").upper().strip()

        broker_minimum_stake = cls.DERIV_DEFAULT_MIN_STAKE
        risk_minimum_required = cls.ZERO
        suggested_minimum_stake = broker_minimum_stake

        return {
            "ok": True,
            "reason": "deriv_stake_based_contract",
            "broker_minimum_stake": cls._money_up(broker_minimum_stake),
            "risk_minimum_required": cls._money_up(risk_minimum_required),
            "suggested_minimum_stake": cls._money_up(suggested_minimum_stake),
            "min_qty": cls.ZERO,
            "qty_step": cls.ZERO,
            "min_notional": cls.ZERO,
            "symbol": symbol,
            "note": "Deriv utilise une mise fixe/stake. On ne calcule pas prix × quantité.",
        }

    @classmethod
    def resolve_constraint(cls, broker_account, symbol: str):
        constraint = (
            BrokerConstraint.objects
            .filter(broker=broker_account.broker, symbol=symbol)
            .first()
        )
        if constraint:
            return constraint

        try:
            return BrokerConstraintSyncService.sync_symbol_constraint(
                broker_account=broker_account,
                symbol=symbol,
            )
        except Exception:
            return None

    @classmethod
    def estimate_minimum_stake(cls, *, idea, broker_account) -> dict:
        symbol = str(getattr(idea, "symbol", "") or "").upper().strip()

        # IMPORTANT :
        # Deriv ne fonctionne pas comme Binance/spot.
        # Pour JD25, R_100, CRASH1000, BOOM, STEP, etc.,
        # la mise est un stake fixe, pas entry_price × min_qty.
        if cls._is_deriv_broker(broker_account):
            return cls._estimate_deriv_minimum_stake(
                idea=idea,
                broker_account=broker_account,
            )

        entry = cls._d(getattr(idea, "entry_price", None))
        stop = cls._d(getattr(idea, "stop_loss", None))

        constraint = cls.resolve_constraint(broker_account, symbol)

        min_qty = cls._d(getattr(constraint, "min_qty", None), str(cls.DEFAULT_MIN_QTY))
        qty_step = cls._d(getattr(constraint, "qty_step", None), str(cls.DEFAULT_QTY_STEP))
        min_notional = cls._d(getattr(constraint, "min_notional", None), str(cls.DEFAULT_MIN_NOTIONAL))

        if entry <= cls.ZERO:
            return {
                "ok": False,
                "reason": "entry_invalid",
                "broker_minimum_stake": cls.ZERO,
                "risk_minimum_required": cls.ZERO,
                "suggested_minimum_stake": cls.ZERO,
                "min_qty": min_qty,
                "qty_step": qty_step,
                "min_notional": min_notional,
            }

        broker_minimum_stake = cls._money_up(
            max(entry * min_qty, min_notional, cls.ZERO)
        )

        if stop > cls.ZERO and stop != entry:
            risk_minimum_required = cls._money_up(abs(entry - stop) * min_qty)
        else:
            risk_minimum_required = cls.ZERO

        suggested_minimum_stake = max(broker_minimum_stake, risk_minimum_required)

        return {
            "ok": True,
            "reason": "spot_notional_based_constraint",
            "broker_minimum_stake": broker_minimum_stake,
            "risk_minimum_required": risk_minimum_required,
            "suggested_minimum_stake": suggested_minimum_stake,
            "min_qty": min_qty,
            "qty_step": qty_step,
            "min_notional": min_notional,
        }