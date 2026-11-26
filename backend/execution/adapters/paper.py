from __future__ import annotations

from decimal import Decimal
from django.utils import timezone

from .base import BaseBrokerAdapter


def _positive(value) -> Decimal | None:
    """Montant strictement positif, ou None."""
    try:
        amount = Decimal(value or 0)
    except Exception:
        return None
    return amount if amount > 0 else None


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

        # Le notionnel vient du montant APPROUVÉ quand il existe, pas d'un
        # produit prix × quantité. `approved_quantity` n'a pas d'unité
        # garantie — plusieurs chemins y écrivent un montant en devise —
        # et le produit donne alors un nombre sans rapport avec
        # l'opération voulue : 20 000 USD sur BTCUSDT à 78 776 avaient
        # produit un débit de 1 575 532 400 au grand livre.
        #
        # La branche Deriv faisait déjà ce choix ; elle n'était simplement
        # pas généralisée.
        approved_notional = _positive(order.approved_notional)
        deriv_stake = _positive(order.requested_stake_amount)

        if is_deriv_contract and deriv_stake is not None:
            notional = deriv_stake
        elif approved_notional is not None:
            notional = approved_notional
        else:
            # Dernier recours seulement : ce produit n'a de sens que si
            # `approved_quantity` porte bien une quantité.
            notional = fill_price * fill_qty
        notional = Decimal(notional).quantize(Decimal("0.01"))

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
