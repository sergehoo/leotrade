from __future__ import annotations

from decimal import Decimal
from django.utils import timezone

from .base import BaseBrokerAdapter


class PaperBrokerAdapter(BaseBrokerAdapter):
    def submit_order(self, order):
        now = timezone.now()
        fill_price = order.requested_price or order.limit_price or Decimal("0")
        fill_qty = order.approved_quantity
        notional = (fill_price * fill_qty).quantize(Decimal("0.01"))

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
                    "metadata": {"engine": "paper"},
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

    def fetch_open_orders(self):
        return []

    def fetch_positions(self):
        return []

    def fetch_balance(self):
        return None