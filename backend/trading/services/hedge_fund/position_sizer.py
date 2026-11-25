# /Users/ogahserge/Documents/leoTrade/trading/services/hedge_fund/position_sizer.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_DOWN

from trading.models_hedge_fund import RiskPolicy


@dataclass
class PositionSizeResult:
    risk_percent: Decimal
    balance: Decimal
    effective_balance: Decimal
    risk_capital: Decimal
    entry_price: Decimal
    stop_loss: Decimal | None
    unit_risk: Decimal
    raw_size: Decimal
    adjusted_size: Decimal
    notional: Decimal
    min_qty: Decimal
    qty_step: Decimal
    min_notional: Decimal
    minimum_stake_required: Decimal
    broker_compatible: bool
    reason: str


class IntelligentPositionSizer:
    SIZE_PRECISION = Decimal("0.0001")
    MONEY_PRECISION = Decimal("0.01")
    HUNDRED = Decimal("100")
    ONE = Decimal("1")
    ZERO = Decimal("0")

    DEFAULT_MIN_QTY = Decimal("0.00000001")
    DEFAULT_QTY_STEP = Decimal("0.00000001")
    DEFAULT_MIN_NOTIONAL = Decimal("0")

    @staticmethod
    def _to_decimal(value, default: str = "0") -> Decimal:
        try:
            if value is None or value == "":
                return Decimal(default)
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal(default)

    @classmethod
    def _quantize_down(cls, value: Decimal, step: Decimal) -> Decimal:
        if step <= cls.ZERO:
            step = cls.SIZE_PRECISION
        try:
            units = (value / step).to_integral_value(rounding=ROUND_DOWN)
            return units * step
        except Exception:
            return cls.ZERO

    @classmethod
    def _quantize_up_money(cls, value: Decimal) -> Decimal:
        try:
            return value.quantize(cls.MONEY_PRECISION, rounding=ROUND_CEILING)
        except Exception:
            return cls.ZERO

    @classmethod
    def _compute_effective_balance(cls, portfolio, policy, balance: Decimal) -> Decimal:
        effective_balance = balance

        allow_auto_compounding = bool(getattr(policy, "allow_auto_compounding", False))
        if not allow_auto_compounding:
            return effective_balance

        starting_balance = cls._to_decimal(getattr(portfolio, "starting_balance", balance))
        growth = balance - starting_balance

        if growth <= cls.ZERO:
            return effective_balance

        compounding_cap_percent = cls._to_decimal(getattr(policy, "compounding_cap_percent", 100))
        cap_ratio = compounding_cap_percent / cls.HUNDRED

        if cap_ratio < cls.ZERO:
            cap_ratio = cls.ZERO
        elif cap_ratio > cls.ONE:
            cap_ratio = cls.ONE

        effective_balance = balance - max(
            cls.ZERO,
            growth * (cls.ONE - cap_ratio)
        )
        return max(cls.ZERO, effective_balance)

    @classmethod
    def _compute_risk_percent(cls, policy, confidence_assessment, risk_state) -> Decimal:
        recommended_risk_percent = getattr(risk_state, "recommended_risk_percent", None)
        base_risk_percent = getattr(policy, "base_risk_per_trade_percent", 0)

        risk_percent = cls._to_decimal(
            recommended_risk_percent if recommended_risk_percent not in (None, "") else base_risk_percent
        )

        final_confidence = float(getattr(confidence_assessment, "final_confidence", 0) or 0)

        if final_confidence >= 0.85:
            risk_percent *= Decimal("1.15")
        elif final_confidence <= 0.60:
            risk_percent *= Decimal("0.75")

        min_risk = cls._to_decimal(getattr(policy, "min_risk_per_trade_percent", 0))
        max_risk = cls._to_decimal(getattr(policy, "max_risk_per_trade_percent", 100))

        if max_risk < min_risk:
            max_risk = min_risk

        return max(min_risk, min(max_risk, risk_percent))

    @classmethod
    def compute_details(
        cls,
        portfolio,
        idea,
        confidence_assessment,
        risk_state,
        *,
        min_qty: Decimal | None = None,
        qty_step: Decimal | None = None,
        min_notional: Decimal | None = None,
    ) -> PositionSizeResult:
        policy, _ = RiskPolicy.objects.get_or_create(portfolio=portfolio)

        balance = cls._to_decimal(getattr(portfolio, "current_balance", 0))
        if balance <= cls.ZERO:
            return PositionSizeResult(
                risk_percent=cls.ZERO,
                balance=balance,
                effective_balance=cls.ZERO,
                risk_capital=cls.ZERO,
                entry_price=cls.ZERO,
                stop_loss=None,
                unit_risk=cls.ZERO,
                raw_size=cls.ZERO,
                adjusted_size=cls.ZERO,
                notional=cls.ZERO,
                min_qty=cls._to_decimal(min_qty, str(cls.DEFAULT_MIN_QTY)),
                qty_step=cls._to_decimal(qty_step, str(cls.DEFAULT_QTY_STEP)),
                min_notional=cls._to_decimal(min_notional, str(cls.DEFAULT_MIN_NOTIONAL)),
                minimum_stake_required=cls.ZERO,
                broker_compatible=False,
                reason="balance_non_positive",
            )

        risk_percent = cls._compute_risk_percent(policy, confidence_assessment, risk_state)
        effective_balance = cls._compute_effective_balance(portfolio, policy, balance)

        if effective_balance <= cls.ZERO:
            return PositionSizeResult(
                risk_percent=risk_percent,
                balance=balance,
                effective_balance=effective_balance,
                risk_capital=cls.ZERO,
                entry_price=cls.ZERO,
                stop_loss=None,
                unit_risk=cls.ZERO,
                raw_size=cls.ZERO,
                adjusted_size=cls.ZERO,
                notional=cls.ZERO,
                min_qty=cls._to_decimal(min_qty, str(cls.DEFAULT_MIN_QTY)),
                qty_step=cls._to_decimal(qty_step, str(cls.DEFAULT_QTY_STEP)),
                min_notional=cls._to_decimal(min_notional, str(cls.DEFAULT_MIN_NOTIONAL)),
                minimum_stake_required=cls.ZERO,
                broker_compatible=False,
                reason="effective_balance_non_positive",
            )

        risk_capital = effective_balance * (risk_percent / cls.HUNDRED)
        if risk_capital <= cls.ZERO:
            return PositionSizeResult(
                risk_percent=risk_percent,
                balance=balance,
                effective_balance=effective_balance,
                risk_capital=risk_capital,
                entry_price=cls.ZERO,
                stop_loss=None,
                unit_risk=cls.ZERO,
                raw_size=cls.ZERO,
                adjusted_size=cls.ZERO,
                notional=cls.ZERO,
                min_qty=cls._to_decimal(min_qty, str(cls.DEFAULT_MIN_QTY)),
                qty_step=cls._to_decimal(qty_step, str(cls.DEFAULT_QTY_STEP)),
                min_notional=cls._to_decimal(min_notional, str(cls.DEFAULT_MIN_NOTIONAL)),
                minimum_stake_required=cls.ZERO,
                broker_compatible=False,
                reason="risk_capital_non_positive",
            )

        entry = cls._to_decimal(getattr(idea, "entry_price", 0))
        stop = cls._to_decimal(getattr(idea, "stop_loss", None), "0")
        stop_value = stop if stop > cls.ZERO else None

        broker_min_qty = cls._to_decimal(min_qty, str(cls.DEFAULT_MIN_QTY))
        broker_qty_step = cls._to_decimal(qty_step, str(cls.DEFAULT_QTY_STEP))
        broker_min_notional = cls._to_decimal(min_notional, str(cls.DEFAULT_MIN_NOTIONAL))

        if entry <= cls.ZERO:
            return PositionSizeResult(
                risk_percent=risk_percent,
                balance=balance,
                effective_balance=effective_balance,
                risk_capital=risk_capital,
                entry_price=entry,
                stop_loss=stop_value,
                unit_risk=cls.ZERO,
                raw_size=cls.ZERO,
                adjusted_size=cls.ZERO,
                notional=cls.ZERO,
                min_qty=broker_min_qty,
                qty_step=broker_qty_step,
                min_notional=broker_min_notional,
                minimum_stake_required=cls.ZERO,
                broker_compatible=False,
                reason="entry_non_positive",
            )

        if stop_value is not None and stop_value != entry:
            unit_risk = abs(entry - stop_value)
            if unit_risk <= cls.ZERO:
                raw_size = cls.ZERO
                minimum_by_risk = cls.ZERO
            else:
                raw_size = risk_capital / unit_risk
                minimum_by_risk = unit_risk * broker_min_qty
        else:
            unit_risk = cls.ZERO
            raw_size = risk_capital / entry
            minimum_by_risk = entry * broker_min_qty

        if raw_size <= cls.ZERO:
            return PositionSizeResult(
                risk_percent=risk_percent,
                balance=balance,
                effective_balance=effective_balance,
                risk_capital=risk_capital,
                entry_price=entry,
                stop_loss=stop_value,
                unit_risk=unit_risk,
                raw_size=cls.ZERO,
                adjusted_size=cls.ZERO,
                notional=cls.ZERO,
                min_qty=broker_min_qty,
                qty_step=broker_qty_step,
                min_notional=broker_min_notional,
                minimum_stake_required=cls._quantize_up_money(max(minimum_by_risk, broker_min_notional)),
                broker_compatible=False,
                reason="raw_size_non_positive",
            )

        adjusted_size = cls._quantize_down(raw_size, broker_qty_step)
        if adjusted_size <= cls.ZERO:
            return PositionSizeResult(
                risk_percent=risk_percent,
                balance=balance,
                effective_balance=effective_balance,
                risk_capital=risk_capital,
                entry_price=entry,
                stop_loss=stop_value,
                unit_risk=unit_risk,
                raw_size=raw_size,
                adjusted_size=cls.ZERO,
                notional=cls.ZERO,
                min_qty=broker_min_qty,
                qty_step=broker_qty_step,
                min_notional=broker_min_notional,
                minimum_stake_required=cls._quantize_up_money(max(minimum_by_risk, broker_min_notional)),
                broker_compatible=False,
                reason="adjusted_size_non_positive",
            )

        notional = adjusted_size * entry
        minimum_stake_required = cls._quantize_up_money(max(minimum_by_risk, broker_min_notional))

        broker_compatible = True
        reason = "ok"

        if adjusted_size < broker_min_qty:
            broker_compatible = False
            reason = "below_min_qty"
        elif notional < broker_min_notional:
            broker_compatible = False
            reason = "below_min_notional"

        try:
            adjusted_size = adjusted_size.quantize(cls.SIZE_PRECISION, rounding=ROUND_DOWN)
        except Exception:
            adjusted_size = cls.ZERO
            broker_compatible = False
            reason = "quantize_failed"

        return PositionSizeResult(
            risk_percent=risk_percent,
            balance=balance,
            effective_balance=effective_balance,
            risk_capital=risk_capital,
            entry_price=entry,
            stop_loss=stop_value,
            unit_risk=unit_risk,
            raw_size=raw_size,
            adjusted_size=adjusted_size,
            notional=notional,
            min_qty=broker_min_qty,
            qty_step=broker_qty_step,
            min_notional=broker_min_notional,
            minimum_stake_required=minimum_stake_required,
            broker_compatible=broker_compatible,
            reason=reason,
        )

    @classmethod
    def compute_size(
        cls,
        portfolio,
        idea,
        confidence_assessment,
        risk_state,
        *,
        min_qty: Decimal | None = None,
        qty_step: Decimal | None = None,
        min_notional: Decimal | None = None,
    ) -> Decimal:
        result = cls.compute_details(
            portfolio=portfolio,
            idea=idea,
            confidence_assessment=confidence_assessment,
            risk_state=risk_state,
            min_qty=min_qty,
            qty_step=qty_step,
            min_notional=min_notional,
        )
        return max(cls.ZERO, result.adjusted_size)