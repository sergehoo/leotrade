from __future__ import annotations

from decimal import Decimal
from django.utils import timezone

from .base import BaseBrokerAdapter


class PaperBrokerAdapter(BaseBrokerAdapter):
    def submit_order(self, order):
        now = timezone.now()
        broker_account = getattr(order, "broker_account", None) or self.broker_account
        is_deriv_contract = getattr(broker_account, "broker", None) == "DERIV"
        fill_price = (
            order.requested_stake_amount
            if is_deriv_contract
            else order.requested_price or order.limit_price or Decimal("0")
        )
        if fill_price <= 0:
            raise ValueError(
                "Paper execution requires a strictly positive reference price."
            )
        fill_qty = Decimal("1") if is_deriv_contract else order.approved_quantity
        notional = (
            order.requested_stake_amount
            if is_deriv_contract
            else fill_price * fill_qty
        ).quantize(Decimal("0.01"))

        return {
            "broker_order_id": f"PAPER-{order.id}",
            "broker_client_order_id": order.idempotency_key,
            "status": "FILLED",
            "submitted_at": now,
            "fills": [
                {
                    "broker_fill_id": f"PAPER-FILL-{order.id}",
                    "quantity": fill_qty,
                    "price": fill_price,
                    "notional": notional,
                    "fee": order.estimated_fee or Decimal("0.00"),
                    "fee_currency": order.portfolio.base_currency,
                    "fill_time": now,
                    "liquidity_type": "TAKER",
                    "metadata": {
                        "engine": "paper",
                        "deriv_contract": is_deriv_contract,
                    },
                }
            ],
            "raw": {"engine": "paper", "mode": "simulated"},
        }

    def cancel_order(self, order):
        return {
            "broker_order_id": order.broker_order_id or f"PAPER-{order.id}",
            "status": "CANCELLED",
            "cancelled_at": timezone.now(),
            "raw": {"engine": "paper"},
        }

    def close_position(self, position, order):
        expected_side = "SELL" if position.side == "LONG" else "BUY"
        if order.side != expected_side:
            raise ValueError("Paper close order side does not reduce the target position.")
        if order.approved_quantity > position.quantity:
            raise ValueError("Paper close quantity exceeds the target position.")
        return self.submit_order(order)

    def fetch_open_orders(self):
        return []

    def fetch_order(self, order):
        if not order.broker_order_id:
            return None
        return {
            "broker_order_id": order.broker_order_id,
            "broker_client_order_id": order.broker_client_order_id,
            "symbol": order.symbol,
            "status": order.status,
            "fills": [],
            "raw": {"engine": "paper", "recovered": True},
        }

    def fetch_positions(self):
        return []

    def fetch_balance(self):
        return None
