from __future__ import annotations

import logging
from contextlib import contextmanager
from decimal import Decimal
from datetime import datetime, timedelta, timezone

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

from core.concurrency import RedisLock
from core.precision import normalize_order
from infrastructure.broker_clients.base import BaseBrokerClient
from infrastructure.broker_clients.dto import (
    BrokerBalanceDTO,
    BrokerPositionDTO,
    BrokerConstraintDTO,
)


logger = logging.getLogger(__name__)


# The MetaTrader5 module is a process-wide singleton. Two workers calling
# ``mt5.initialize()`` / ``mt5.login()`` / ``mt5.order_send()`` in parallel
# corrupt the terminal state and produce phantom errors. We serialize ALL
# calls per broker_account via a Redis lock — local fallback in dev only.
_MT5_LOCK_TIMEOUT_SECONDS = 60


@contextmanager
def _mt5_session(broker_account_id: int):
    lock = RedisLock(
        f"broker:mt5:{broker_account_id}",
        timeout=_MT5_LOCK_TIMEOUT_SECONDS,
        blocking=True,
        blocking_timeout=30.0,
    )
    if not lock.acquire():
        raise RuntimeError(
            f"Timeout acquiring MT5 session lock for account {broker_account_id}."
        )
    try:
        yield
    finally:
        lock.release()


def _d(value, default="0"):
    try:
        if value is None:
            return Decimal(default)
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _ts_to_dt(ts):
    if not ts:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(ts, tz=timezone.utc)


class MT5BrokerClient(BaseBrokerClient):
    """
    Client MetaTrader 5 sécurisé :
    - n'explose pas au chargement du module si MetaTrader5 n'est pas installé
    - ne tente la connexion MT5 qu'au moment de l'instanciation
    - propose un shutdown propre
    """

    def __init__(self, broker_account):
        super().__init__(broker_account)

        if mt5 is None:
            raise RuntimeError(
                "Le package MetaTrader5 n'est pas installé dans cet environnement. "
                "Installe-le avec `pip install MetaTrader5` sur une machine compatible, "
                "ou désactive le broker MT5."
            )

        self._initialized = False
        # Login under the global mt5 lock to avoid concurrent
        # initialize/login from multiple workers corrupting the terminal.
        with _mt5_session(self.broker_account.id):
            self._login()

    def _login(self):
        terminal_path = self.broker_account.terminal_path or None

        ok = mt5.initialize(path=terminal_path)
        if not ok:
            raise ValueError(f"MT5 initialize failed: {mt5.last_error()}")

        self._initialized = True

        password = self.broker_account.password
        login_raw = self.broker_account.login
        server = self.broker_account.server

        if not login_raw:
            self.shutdown()
            raise ValueError("MT5 login manquant.")

        if not password:
            self.shutdown()
            raise ValueError("MT5 password manquant.")

        if not server:
            self.shutdown()
            raise ValueError("MT5 server manquant.")

        try:
            login = int(login_raw)
        except (TypeError, ValueError):
            self.shutdown()
            raise ValueError("MT5 login invalide : doit être un entier.")

        authorized = mt5.login(login=login, password=password, server=server)
        if not authorized:
            error = mt5.last_error()
            self.shutdown()
            raise ValueError(f"MT5 login failed: {error}")

    def shutdown(self):
        if self._initialized and mt5 is not None:
            try:
                mt5.shutdown()
            except Exception:
                pass
            self._initialized = False

    def __del__(self):
        self.shutdown()

    def test_connection(self):
        info = mt5.account_info()
        if info is None:
            raise ValueError(f"MT5 account_info failed: {mt5.last_error()}")
        return info._asdict()

    def fetch_balances(self):
        info = mt5.account_info()
        if info is None:
            raise RuntimeError(f"MT5 account_info failed: {mt5.last_error()}")

        return [
            BrokerBalanceDTO(
                currency=str(getattr(info, "currency", "USD")),
                total=_d(getattr(info, "balance", 0)),
                available=_d(getattr(info, "margin_free", 0)),
                locked=max(Decimal("0"), _d(getattr(info, "margin", 0))),
            )
        ]

    def fetch_positions(self):
        rows = mt5.positions_get()
        if rows is None:
            raise RuntimeError(f"MT5 positions_get failed: {mt5.last_error()}")

        positions = []
        for row in rows:
            d = row._asdict()
            side = "LONG" if int(d.get("type", 0)) == 0 else "SHORT"
            qty = _d(d.get("volume"))
            price_open = _d(d.get("price_open"))
            price_current = _d(d.get("price_current"))
            symbol = d.get("symbol")

            positions.append(
                BrokerPositionDTO(
                    symbol=symbol,
                    side=side,
                    quantity=qty,
                    entry_price=price_open,
                    current_price=price_current,
                    average_entry_price=price_open,
                    leverage=Decimal("1"),
                    margin_used=(_d(d.get("price_open")) * qty).quantize(Decimal("0.01")),
                    broker_position_id=str(d.get("ticket")),
                    cost_basis_status="KNOWN",
                    metadata=d,
                )
            )
        return positions

    def fetch_open_orders(self):
        rows = mt5.orders_get()
        if rows is None:
            raise RuntimeError(f"MT5 orders_get failed: {mt5.last_error()}")

        payload = []
        for row in rows:
            d = row._asdict()
            payload.append({
                "broker_order_id": str(d.get("ticket")),
                "broker_client_order_id": str(d.get("magic") or ""),
                "symbol": d.get("symbol"),
                "status": "SUBMITTED",
                "fills": [],
                "raw": d,
            })
        return payload

    def fetch_order(self, order):
        expected_comments = {f"LT-{order.id}", f"LT-close-{order.id}"}
        now = datetime.now(timezone.utc)

        with _mt5_session(self.broker_account.id):
            rows = []
            if order.broker_order_id:
                rows.extend(mt5.orders_get(ticket=int(order.broker_order_id)) or [])
                rows.extend(
                    mt5.history_orders_get(ticket=int(order.broker_order_id)) or []
                )
            else:
                rows.extend(mt5.orders_get(symbol=order.symbol) or [])
                history = mt5.history_orders_get(
                    now - timedelta(days=7),
                    now,
                    group=f"*{order.symbol}*",
                ) or []
                rows.extend(history)

            matched = None
            for row in rows:
                payload = row._asdict()
                if order.broker_order_id and str(payload.get("ticket")) == str(
                    order.broker_order_id
                ):
                    matched = payload
                    break
                if str(payload.get("comment") or "") in expected_comments:
                    matched = payload
                    break

            if matched is None:
                return None

            ticket = matched.get("ticket")
            deals = mt5.history_deals_get(order=int(ticket)) or []

        fills = []
        for deal in deals:
            payload = deal._asdict()
            quantity = _d(payload.get("volume"))
            price = _d(payload.get("price"))
            if quantity <= 0 or price <= 0:
                continue
            fills.append({
                "broker_fill_id": str(payload.get("ticket")),
                "quantity": quantity,
                "price": price,
                "notional": (quantity * price).quantize(Decimal("0.01")),
                "fee": abs(_d(payload.get("commission"))) + abs(_d(payload.get("fee"))),
                "fee_currency": order.portfolio.base_currency,
                "fill_time": _ts_to_dt(payload.get("time")),
                "metadata": payload,
            })

        state = matched.get("state")
        status = "SUBMITTED"
        if fills:
            filled_quantity = sum(
                (_d(fill["quantity"]) for fill in fills),
                start=Decimal("0"),
            )
            status = (
                "FILLED"
                if filled_quantity >= _d(order.approved_quantity)
                else "PARTIALLY_FILLED"
            )
        else:
            state_map = {
                getattr(mt5, "ORDER_STATE_CANCELED", object()): "CANCELLED",
                getattr(mt5, "ORDER_STATE_REJECTED", object()): "REJECTED",
                getattr(mt5, "ORDER_STATE_EXPIRED", object()): "EXPIRED",
                getattr(mt5, "ORDER_STATE_FILLED", object()): "FILLED",
                getattr(mt5, "ORDER_STATE_PARTIAL", object()): "PARTIALLY_FILLED",
            }
            status = state_map.get(state, "SUBMITTED")

        return {
            "broker_order_id": str(ticket),
            "broker_client_order_id": str(matched.get("magic") or ""),
            "symbol": matched.get("symbol") or order.symbol,
            "status": status,
            "fills": fills,
            "raw": matched,
        }

    def _select_filling_mode(self, symbol_info):
        """
        Choose a filling mode supported by the symbol.

        FIX: previous code hardcoded ``ORDER_FILLING_IOC`` which is rejected
        by some brokers (e.g. ECN MT5 servers expecting FOK or RETURN).
        We honor the symbol's ``filling_mode`` bitmask.
        """
        mask = int(getattr(symbol_info, "filling_mode", 0) or 0)
        # MT5 docs: 1=FOK, 2=IOC, 4=RETURN
        if mask & 1 and getattr(mt5, "ORDER_FILLING_FOK", None) is not None:
            return mt5.ORDER_FILLING_FOK
        if mask & 2 and getattr(mt5, "ORDER_FILLING_IOC", None) is not None:
            return mt5.ORDER_FILLING_IOC
        if mask & 4 and getattr(mt5, "ORDER_FILLING_RETURN", None) is not None:
            return mt5.ORDER_FILLING_RETURN
        return getattr(mt5, "ORDER_FILLING_IOC", 0)

    def _stable_magic(self, broker_account_id: int) -> int:
        """Generate a stable per-account magic number to identify our orders."""
        return 200_000_000 + (int(broker_account_id) % 10_000_000)

    def submit_order(self, order):
        with _mt5_session(self.broker_account.id):
            symbol = order.symbol
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                raise ValueError(f"Symbole MT5 introuvable: {symbol}")

            if not symbol_info.visible:
                selected = mt5.symbol_select(symbol, True)
                if not selected:
                    raise ValueError(
                        f"Impossible de rendre visible le symbole MT5: {symbol}"
                    )

            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                raise ValueError(f"Tick introuvable pour {symbol}")

            # ──────────────────────────────────────────────────────────────
            # Garde d'unité — OUVERTURE UNIQUEMENT.
            #
            # `request["volume"]` est exprimé en LOTS : 1 lot vaut
            # `trade_contract_size` unités du sous-jacent (100 000 sur une
            # paire forex, 100 sur XAUUSD, souvent 1 sur un CFD indice).
            #
            # `order.approved_quantity`, lui, n'a pas d'unité garantie. Trois
            # producteurs y écrivent des grandeurs différentes :
            #   - risk/services.py (PositionSizingService) : une quantité en
            #     unités de sous-jacent (montant / prix) ;
            #   - risk/services.py:1010, chemin Deriv : un MONTANT en devise ;
            #   - market/views.py:644, Quick Trade : un MONTANT en devise.
            # cf. la note d'invariant sur Order.approved_quantity.
            #
            # Tant que cet invariant n'est pas établi en amont, convertir
            # serait pire que refuser : sur un Quick Trade MT5, un montant de
            # 500 USD divisé par 100 000 donnerait 0,005 lot — un ordre
            # parfaitement valide pour le broker, donc EXÉCUTÉ, là où
            # aujourd'hui « 500 lots » est rejeté bruyamment. On transformerait
            # un échec visible en trade silencieusement faux.
            #
            # On refuse donc d'OUVRIR quand on ne peut pas prouver que
            # 1 lot = 1 unité. La valeur est lue en direct sur le terminal,
            # sans passer par BrokerConstraint : pas de dépendance à une table
            # qui peut être vide ou périmée.
            #
            # La fermeture (close_position) n'est délibérément PAS gardée :
            # refuser une sortie détruirait du capital au lieu d'en protéger.
            raw_contract_size = getattr(symbol_info, "trade_contract_size", None)
            if raw_contract_size is None or _d(raw_contract_size) != Decimal("1"):
                raise ValueError(
                    f"MT5 {symbol}: ouverture refusée — taille de contrat "
                    f"{raw_contract_size!r} non unitaire. La quantité interne "
                    f"est exprimée en unités de sous-jacent et serait envoyée "
                    f"telle quelle dans un champ en lots, soit une erreur de "
                    f"dimensionnement d'un facteur {raw_contract_size!r}. "
                    f"La fermeture des positions existantes reste autorisée."
                )

            # Round volume to symbol step before sending (prevents broker rejects).
            normalized = normalize_order(
                quantity=order.approved_quantity,
                price=tick.ask if order.side == "BUY" else tick.bid,
                min_qty=Decimal(str(symbol_info.volume_min or 0.01)),
                qty_step=Decimal(str(symbol_info.volume_step or 0.01)),
                price_tick=Decimal(str(symbol_info.point or 0.00001)),
                # Borne haute absente jusqu'ici : rien côté application
                # n'empêchait un ordre surdimensionné de partir au broker.
                max_qty=Decimal(str(symbol_info.volume_max or 0)),
            )
            if not normalized.ok:
                raise ValueError(f"MT5 precision rejected: {normalized.reason}")

            if order.side == "BUY":
                order_type = mt5.ORDER_TYPE_BUY
                price = _d(tick.ask)
            else:
                order_type = mt5.ORDER_TYPE_SELL
                price = _d(tick.bid)

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(normalized.quantity),
                "type": order_type,
                "price": float(price),
                "sl": float(order.stop_loss) if order.stop_loss else 0.0,
                "tp": float(order.take_profit) if order.take_profit else 0.0,
                "deviation": 20,
                "magic": self._stable_magic(self.broker_account.id),
                "comment": f"LT-{order.id}",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": self._select_filling_mode(symbol_info),
            }

            result = mt5.order_send(request)
            if result is None:
                raise ValueError(f"MT5 order_send failed: {mt5.last_error()}")

            result_dict = result._asdict()
            retcode = result_dict.get("retcode")

            accepted_codes = {
                getattr(mt5, "TRADE_RETCODE_DONE", None),
                getattr(mt5, "TRADE_RETCODE_PLACED", None),
                getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", None),
            }

            if retcode not in accepted_codes:
                raise ValueError(f"MT5 order rejected: {result_dict}")

            fills = []
            deal_volume = _d(result_dict.get("volume"))
            deal_price = _d(result_dict.get("price"))

            if deal_volume > 0 and deal_price > 0:
                fills.append({
                    "broker_fill_id": str(result_dict.get("deal") or ""),
                    "quantity": deal_volume,
                    "price": deal_price,
                    "notional": (deal_volume * deal_price).quantize(Decimal("0.01")),
                    "fee": Decimal("0.00"),
                    "fee_currency": order.portfolio.base_currency,
                    "fill_time": datetime.now(timezone.utc),
                    "liquidity_type": None,
                    "metadata": result_dict,
                })

            status = "FILLED" if fills else "SUBMITTED"

            return {
                "broker_order_id": str(result_dict.get("order") or ""),
                "broker_client_order_id": str(request["magic"]),
                "status": status,
                "submitted_at": datetime.now(timezone.utc),
                "fills": fills,
                "raw": result_dict,
            }

    def close_position(self, position, order):
        position_ticket = position.broker_position_id or position.broker_order_id
        if not position_ticket:
            raise ValueError(
                "MT5 broker_position_id manquant; fermeture automatique refusée."
            )

        with _mt5_session(self.broker_account.id):
            broker_positions = mt5.positions_get(ticket=int(position_ticket))
            if not broker_positions:
                raise ValueError(f"Position MT5 introuvable: {position_ticket}")

            broker_position = broker_positions[0]
            if broker_position.symbol != position.symbol:
                raise ValueError("MT5 close symbol does not match the target position.")

            symbol_info = mt5.symbol_info(position.symbol)
            tick = mt5.symbol_info_tick(position.symbol)
            if symbol_info is None or tick is None:
                raise ValueError(f"Tick MT5 introuvable pour {position.symbol}")

            expected_side = (
                "SELL"
                if broker_position.type == mt5.POSITION_TYPE_BUY
                else "BUY"
            )
            if order.side != expected_side:
                raise ValueError("MT5 close order side does not reduce the broker position.")

            requested_quantity = _d(order.approved_quantity)
            broker_quantity = _d(broker_position.volume)
            if requested_quantity <= 0 or requested_quantity > broker_quantity:
                raise ValueError("MT5 close quantity exceeds the broker position.")

            normalized = normalize_order(
                quantity=requested_quantity,
                price=tick.bid if expected_side == "SELL" else tick.ask,
                min_qty=Decimal(str(symbol_info.volume_min or 0.01)),
                qty_step=Decimal(str(symbol_info.volume_step or 0.01)),
                price_tick=Decimal(str(symbol_info.point or 0.00001)),
            )
            if not normalized.ok:
                raise ValueError(f"MT5 close precision rejected: {normalized.reason}")

            order_type = (
                mt5.ORDER_TYPE_SELL
                if expected_side == "SELL"
                else mt5.ORDER_TYPE_BUY
            )
            price = _d(tick.bid if expected_side == "SELL" else tick.ask)
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": position.symbol,
                "volume": float(normalized.quantity),
                "type": order_type,
                "position": int(position_ticket),
                "price": float(price),
                "deviation": 20,
                "magic": self._stable_magic(self.broker_account.id),
                "comment": f"LT-close-{order.id}",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": self._select_filling_mode(symbol_info),
            }
            result = mt5.order_send(request)
            if result is None:
                raise ValueError(f"MT5 close failed: {mt5.last_error()}")

            result_dict = result._asdict()
            accepted_codes = {
                getattr(mt5, "TRADE_RETCODE_DONE", None),
                getattr(mt5, "TRADE_RETCODE_PLACED", None),
                getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", None),
            }
            if result_dict.get("retcode") not in accepted_codes:
                raise ValueError(f"MT5 close rejected: {result_dict}")

            deal_quantity = _d(result_dict.get("volume"))
            deal_price = _d(result_dict.get("price"))
            fills = []
            if deal_quantity > 0 and deal_price > 0:
                fills.append({
                    "broker_fill_id": str(result_dict.get("deal") or ""),
                    "quantity": deal_quantity,
                    "price": deal_price,
                    "notional": (deal_quantity * deal_price).quantize(Decimal("0.01")),
                    "fee": Decimal("0.00"),
                    "fee_currency": order.portfolio.base_currency,
                    "fill_time": datetime.now(timezone.utc),
                    "liquidity_type": None,
                    "metadata": {**result_dict, "position_ticket": str(position_ticket)},
                })

            return {
                "broker_order_id": str(result_dict.get("order") or position_ticket),
                "broker_client_order_id": str(request["magic"]),
                "status": "FILLED" if fills else "SUBMITTED",
                "submitted_at": datetime.now(timezone.utc),
                "fills": fills,
                "raw": result_dict,
            }

    def cancel_order(self, order):
        """
        Pour annuler un ordre pending MT5.
        Attention: différent de la fermeture d'une position ouverte.
        """
        if not order.broker_order_id:
            raise ValueError("broker_order_id manquant pour annulation MT5.")

        with _mt5_session(self.broker_account.id):
            request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": int(order.broker_order_id),
                "comment": f"LeoTrade-cancel-{order.id}",
            }

            result = mt5.order_send(request)
            if result is None:
                raise ValueError(f"MT5 cancel failed: {mt5.last_error()}")

            result_dict = result._asdict()
            retcode = result_dict.get("retcode")

            accepted_codes = {
                getattr(mt5, "TRADE_RETCODE_DONE", None),
                getattr(mt5, "TRADE_RETCODE_PLACED", None),
            }

            if retcode not in accepted_codes:
                raise ValueError(f"MT5 cancel rejected: {result_dict}")

            return {
                "broker_order_id": str(order.broker_order_id),
                "status": "CANCELLED",
                "cancelled_at": datetime.now(timezone.utc),
                "raw": result_dict,
            }

    def fetch_symbol_constraints(self, symbol: str):
        with _mt5_session(self.broker_account.id):
            info = mt5.symbol_info(symbol)
            if info is None:
                raise ValueError(f"Symbole MT5 introuvable: {symbol}")

            d = info._asdict()
            volume_min = _d(d.get("volume_min", 0.01))
            volume_max = _d(d.get("volume_max", 100))
            volume_step = _d(d.get("volume_step", 0.01))
            tick_size = _d(d.get("point", 0.00001))
            contract_size = _d(d.get("trade_contract_size", 1))

            return BrokerConstraintDTO(
                symbol=symbol,
                min_qty=volume_min,
                max_qty=volume_max,
                qty_step=volume_step,
                min_notional=Decimal("0"),
                price_tick=tick_size,
                leverage_min=Decimal("1"),
                leverage_max=Decimal("100"),
                contract_size=contract_size,
                raw_payload=d,
            )
