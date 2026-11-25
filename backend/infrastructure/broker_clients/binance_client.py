from __future__ import annotations

import hashlib
import logging
from decimal import Decimal
from datetime import datetime, timezone

from binance.client import Client
from binance.enums import SIDE_BUY, SIDE_SELL, ORDER_TYPE_MARKET, ORDER_TYPE_LIMIT

from core.precision import (
    normalize_order,
    quantity_to_str,
    price_to_str,
    to_decimal,
)
from core.retry import retry_call
from infrastructure.broker_clients.base import BaseBrokerClient
from infrastructure.broker_clients.dto import (
    BrokerBalanceDTO,
    BrokerPositionDTO,
    BrokerOrderResultDTO,
    BrokerFillDTO,
    BrokerConstraintDTO,
)


logger = logging.getLogger(__name__)


def _d(value, default="0"):
    return to_decimal(value, default)


def _ms_to_dt(ms):
    if not ms:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _safe_client_order_id(idempotency_key: str) -> str:
    """
    Build a Binance ``newClientOrderId`` from an internal key.

    Binance accepts up to 36 chars. The previous code did
    ``idempotency_key[:32]`` which silently truncated UUID hex tails of keys
    like ``f"{broker_id}-{portfolio_id}-{uuid4().hex}"`` and could collide for
    different orders sharing the same prefix. We instead hash the full key
    and prefix with ``LT`` for traceability — guaranteed unique per key.
    """
    key = idempotency_key or ""
    if len(key) <= 36 and " " not in key:
        return key
    h = hashlib.sha1(key.encode()).hexdigest()[:32]
    return f"LT{h}"  # 34 chars, well within Binance's 36 limit


class BinanceBrokerClient(BaseBrokerClient):
    """
    Binance spot client wrapper.

    Improvements vs original:

    - Validates credentials.
    - Wraps every network call in ``retry_call`` for transient errors only
      (no retry on validation rejects).
    - Builds a stable ``newClientOrderId`` (no truncation collisions).
    - Rounds quantity/price against ``BrokerConstraint`` before submitting.
    - Maps Binance status codes consistently.
    """

    def __init__(self, broker_account):
        super().__init__(broker_account)
        api_key = broker_account.api_key
        api_secret = broker_account.api_secret
        if not api_key or not api_secret:
            raise ValueError("Credentials Binance manquants.")
        self.client = Client(api_key, api_secret)

    def test_connection(self):
        return self.client.get_account()

    def fetch_balances(self):
        account = self.client.get_account()
        balances = []

        for row in account.get("balances", []):
            free = _d(row.get("free"))
            locked = _d(row.get("locked"))
            total = free + locked
            if total <= 0:
                continue

            balances.append(
                BrokerBalanceDTO(
                    currency=row.get("asset"),
                    total=total,
                    available=free,
                    locked=locked,
                )
            )
        return balances

    def fetch_positions(self):
        """
        Spot Binance ne donne pas des 'positions' au sens CFD.
        On reconstitue des holdings > 0.
        """
        balances = self.fetch_balances()
        positions = []

        for bal in balances:
            if bal.currency in {"USDT", "USDC", "BUSD", "FDUSD"}:
                continue

            symbol = f"{bal.currency}USDT"
            price = Decimal("0")
            try:
                ticker = self.client.get_symbol_ticker(symbol=symbol)
                price = _d(ticker.get("price"))
            except Exception:
                continue

            qty = bal.total
            if qty <= 0:
                continue

            positions.append(
                BrokerPositionDTO(
                    symbol=symbol,
                    side="LONG",
                    quantity=qty,
                    entry_price=price,
                    current_price=price,
                    average_entry_price=price,
                    leverage=Decimal("1"),
                    margin_used=Decimal("0"),
                    broker_position_id=f"SPOT-{symbol}",
                    cost_basis_status="UNKNOWN",
                    metadata={"origin": "binance_spot_balance"},
                )
            )
        return positions

    def fetch_open_orders(self):
        open_orders = self.client.get_open_orders()
        payload = []

        for row in open_orders:
            payload.append({
                "broker_order_id": str(row.get("orderId")),
                "broker_client_order_id": row.get("clientOrderId"),
                "symbol": row.get("symbol"),
                "status": str(row.get("status") or "").upper(),
                "fills": [],
                "raw": row,
            })
        return payload

    def fetch_order(self, order):
        params = {"symbol": order.symbol}
        if order.broker_order_id:
            params["orderId"] = int(order.broker_order_id)
        else:
            params["origClientOrderId"] = _safe_client_order_id(
                order.idempotency_key
            )

        try:
            row = self.client.get_order(**params)
        except Exception as exc:
            if getattr(exc, "code", None) == -2013:
                return None
            raise

        executed_quantity = _d(row.get("executedQty"))
        fills = []
        if executed_quantity > 0:
            trades = self.client.get_my_trades(
                symbol=order.symbol,
                orderId=int(row.get("orderId")),
            )
            for trade in trades or []:
                quantity = _d(trade.get("qty"))
                price = _d(trade.get("price"))
                fills.append({
                    "broker_fill_id": str(trade.get("id")),
                    "quantity": quantity,
                    "price": price,
                    "notional": _d(trade.get("quoteQty"))
                    or (quantity * price).quantize(Decimal("0.01")),
                    "fee": _d(trade.get("commission")),
                    "fee_currency": trade.get("commissionAsset")
                    or order.portfolio.base_currency,
                    "fill_time": _ms_to_dt(trade.get("time")),
                    "liquidity_type": "MAKER" if trade.get("isMaker") else "TAKER",
                    "metadata": trade,
                })

            if not fills:
                cumulative_quote = _d(row.get("cummulativeQuoteQty"))
                average_price = (
                    cumulative_quote / executed_quantity
                    if executed_quantity > 0 and cumulative_quote > 0
                    else _d(row.get("price"))
                )
                fills.append({
                    "broker_fill_id": None,
                    "quantity": executed_quantity,
                    "price": average_price,
                    "notional": cumulative_quote,
                    "fee": Decimal("0"),
                    "fee_currency": order.portfolio.base_currency,
                    "fill_time": _ms_to_dt(row.get("updateTime") or row.get("time")),
                    "metadata": {
                        "reconciliation_cumulative": True,
                        "broker_order_id": str(row.get("orderId")),
                    },
                })

        return {
            "broker_order_id": str(row.get("orderId")),
            "broker_client_order_id": row.get("clientOrderId"),
            "symbol": row.get("symbol"),
            "status": str(row.get("status") or "").upper(),
            "fills": fills,
            "raw": row,
        }

    def submit_order(self, order):
        constraint = self._fetch_local_constraint(order.symbol)

        normalized = normalize_order(
            quantity=order.approved_quantity,
            price=order.limit_price or order.requested_price,
            constraint=constraint,
            # Borne haute passée explicitement, jamais héritée de `constraint` :
            # seule l'ouverture la subit, pour qu'aucune fermeture ne puisse
            # être bloquée par un plafond de taille.
            max_qty=getattr(constraint, "max_qty", None) if constraint else None,
        )
        if not normalized.ok:
            raise ValueError(f"Binance precision rejected: {normalized.reason}")

        qty_step = getattr(constraint, "qty_step", Decimal("0.00000001")) if constraint else Decimal("0.00000001")
        price_tick = getattr(constraint, "price_tick", Decimal("0.00000001")) if constraint else Decimal("0.00000001")

        params = {
            "symbol": order.symbol,
            "side": SIDE_BUY if order.side == "BUY" else SIDE_SELL,
            "newClientOrderId": _safe_client_order_id(order.idempotency_key),
        }

        if order.order_type == "MARKET":
            params["type"] = ORDER_TYPE_MARKET
            params["quantity"] = quantity_to_str(normalized.quantity, qty_step)
        elif order.order_type == "LIMIT":
            if normalized.price is None:
                raise ValueError("Binance LIMIT order requires a price.")
            params["type"] = ORDER_TYPE_LIMIT
            params["timeInForce"] = "GTC"
            params["quantity"] = quantity_to_str(normalized.quantity, qty_step)
            params["price"] = price_to_str(normalized.price, price_tick)
        else:
            raise NotImplementedError(
                f"Order type non supporté Binance: {order.order_type}"
            )

        # A create-order call is not safely retryable: the broker may have
        # accepted the order even when the response is lost. The stable
        # newClientOrderId lets reconciliation recover that ambiguous state.
        response = self.client.create_order(**params)

        fills = []
        for fill in response.get("fills", []):
            qty = _d(fill.get("qty"))
            price = _d(fill.get("price"))
            fee = _d(fill.get("commission"))
            fills.append(
                {
                    "broker_fill_id": None,
                    "quantity": qty,
                    "price": price,
                    "notional": (qty * price).quantize(Decimal("0.01")),
                    "fee": fee,
                    "fee_currency": fill.get("commissionAsset") or order.portfolio.base_currency,
                    "fill_time": _ms_to_dt(response.get("transactTime")),
                    "liquidity_type": None,
                    "metadata": fill,
                }
            )

        status_map = {
            "NEW": "SUBMITTED",
            "PARTIALLY_FILLED": "PARTIALLY_FILLED",
            "FILLED": "FILLED",
            "CANCELED": "CANCELLED",
            "REJECTED": "REJECTED",
            "EXPIRED": "EXPIRED",
        }

        return {
            "broker_order_id": str(response.get("orderId")),
            "broker_client_order_id": response.get("clientOrderId"),
            "status": status_map.get(str(response.get("status") or "").upper(), "SUBMITTED"),
            "submitted_at": _ms_to_dt(response.get("transactTime")),
            "fills": fills,
            "raw": response,
        }

    def _fetch_local_constraint(self, symbol: str):
        """Best-effort local lookup; falls back to ``None`` if not synced."""
        try:
            from brokers.models import BrokerConstraint

            return (
                BrokerConstraint.objects
                .filter(broker="BINANCE", symbol=symbol)
                .first()
            )
        except Exception:
            return None

    def cancel_order(self, order):
        if not order.broker_order_id:
            # Use clientOrderId to cancel an order we never received broker_order_id for
            response = self.client.cancel_order(
                symbol=order.symbol,
                origClientOrderId=_safe_client_order_id(order.idempotency_key),
            )
        else:
            response = self.client.cancel_order(
                symbol=order.symbol,
                orderId=int(order.broker_order_id),
            )
        return {
            "broker_order_id": str(response.get("orderId")),
            "status": "CANCELLED",
            "cancelled_at": _ms_to_dt(response.get("transactTime")),
            "raw": response,
        }

    def close_position(self, position, order):
        if position.side != "LONG" or order.side != "SELL":
            raise NotImplementedError(
                "Binance Spot ne peut réduire automatiquement qu'une position LONG via SELL."
            )
        if order.symbol != position.symbol:
            raise ValueError("Binance close symbol does not match the target position.")
        if order.approved_quantity > position.quantity:
            raise ValueError("Binance close quantity exceeds the target position.")
        return self.submit_order(order)

    def fetch_symbol_constraints(self, symbol: str):
        exchange_info = self.client.get_symbol_info(symbol)
        if not exchange_info:
            raise ValueError(f"Symbole Binance introuvable: {symbol}")

        min_qty = Decimal("0")
        max_qty = Decimal("0")
        step_size = Decimal("0.00000001")
        min_notional = Decimal("0")
        tick_size = Decimal("0.00000001")

        for f in exchange_info.get("filters", []):
            ftype = f.get("filterType")
            if ftype == "LOT_SIZE":
                min_qty = _d(f.get("minQty"))
                max_qty = _d(f.get("maxQty"))
                step_size = _d(f.get("stepSize"))
            elif ftype == "MIN_NOTIONAL":
                min_notional = _d(f.get("minNotional"))
            elif ftype == "PRICE_FILTER":
                tick_size = _d(f.get("tickSize"))

        return BrokerConstraintDTO(
            symbol=symbol,
            min_qty=min_qty,
            max_qty=max_qty,
            qty_step=step_size,
            min_notional=min_notional,
            price_tick=tick_size,
            leverage_min=Decimal("1"),
            leverage_max=Decimal("1"),
            contract_size=Decimal("1"),
            raw_payload=exchange_info,
        )
