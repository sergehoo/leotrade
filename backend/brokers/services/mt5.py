# /Users/ogahserge/Documents/leoTrade/brokers/services/mt5.py
from __future__ import annotations

import sys
from typing import Any, Optional

# MetaTrader5 est disponible surtout sur Windows avec terminal installé.
if sys.platform == "win32":
    try:
        import MetaTrader5 as mt5
        MT5_AVAILABLE = True
    except ImportError:
        mt5 = None
        MT5_AVAILABLE = False
else:
    mt5 = None
    MT5_AVAILABLE = False


class MT5ClientError(Exception):
    pass


class MT5Client:
    TIMEFRAME_MAP = {
        "1m": "TIMEFRAME_M1",
        "5m": "TIMEFRAME_M5",
        "15m": "TIMEFRAME_M15",
        "30m": "TIMEFRAME_M30",
        "1h": "TIMEFRAME_H1",
        "4h": "TIMEFRAME_H4",
        "1d": "TIMEFRAME_D1",
        "1w": "TIMEFRAME_W1",
    }

    def __init__(
        self,
        login: int,
        password: str,
        server: str,
        terminal_path: Optional[str] = None,
        timeout: int = 60_000,
    ):
        self.login = int(login)
        self.password = password
        self.server = server
        self.terminal_path = terminal_path
        self.timeout = timeout
        self.connected = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_mt5(self):
        if not MT5_AVAILABLE or mt5 is None:
            raise MT5ClientError(
                "MetaTrader5 n'est disponible que sur Windows avec le terminal MT5 installé. "
                "Sur macOS/Linux, utilisez le paper trading ou un broker REST."
            )

    def _last_error(self) -> str:
        self._require_mt5()
        err = mt5.last_error()
        return str(err)

    def _ensure_connected(self):
        if not self.connected:
            raise MT5ClientError("Le client MT5 n'est pas connecté.")

    def _to_dict(self, value: Any):
        if value is None:
            return None
        if hasattr(value, "_asdict"):
            return value._asdict()
        return value

    def _get_timeframe(self, timeframe):
        self._require_mt5()

        if isinstance(timeframe, int):
            return timeframe

        if isinstance(timeframe, str):
            attr_name = self.TIMEFRAME_MAP.get(timeframe, timeframe)
            tf = getattr(mt5, attr_name, None)
            if tf is None:
                raise MT5ClientError(f"Timeframe MT5 invalide: {timeframe}")
            return tf

        raise MT5ClientError(f"Type de timeframe non supporté: {type(timeframe)}")

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        self._require_mt5()

        ok = mt5.initialize(
            path=self.terminal_path,
            login=self.login,
            password=self.password,
            server=self.server,
            timeout=self.timeout,
        )
        if not ok:
            raise MT5ClientError(f"MT5 initialize/login failed: {self._last_error()}")

        self.connected = True
        return True

    def shutdown(self):
        if MT5_AVAILABLE and mt5:
            mt5.shutdown()
        self.connected = False

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.shutdown()

    def test_connection(self) -> tuple[bool, str]:
        try:
            self.connect()
            info = mt5.account_info()
            if not info:
                return False, f"Impossible de lire account_info: {self._last_error()}"
            return True, ""
        except Exception as exc:
            return False, str(exc)
        finally:
            self.shutdown()

    # ------------------------------------------------------------------
    # Account / terminal info
    # ------------------------------------------------------------------

    def terminal_info(self):
        self._ensure_connected()
        return self._to_dict(mt5.terminal_info())

    def version(self):
        self._ensure_connected()
        return mt5.version()

    def account_info(self):
        self._ensure_connected()
        info = mt5.account_info()
        if not info:
            raise MT5ClientError(f"Impossible de récupérer account_info: {self._last_error()}")
        return info._asdict()

    # ------------------------------------------------------------------
    # Symbol / market data
    # ------------------------------------------------------------------

    def symbol_info(self, symbol: str):
        self._ensure_connected()
        info = mt5.symbol_info(symbol)
        if not info:
            raise MT5ClientError(f"Symbole introuvable: {symbol}")
        return info._asdict()

    def symbol_tick(self, symbol: str):
        self._ensure_connected()
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            raise MT5ClientError(f"Tick introuvable pour {symbol}")
        return tick._asdict()

    def ensure_symbol(self, symbol: str) -> bool:
        self._ensure_connected()

        info = mt5.symbol_info(symbol)
        if info is None:
            raise MT5ClientError(f"Symbole non disponible dans MT5: {symbol}")

        if not info.visible:
            ok = mt5.symbol_select(symbol, True)
            if not ok:
                raise MT5ClientError(f"Impossible d'activer le symbole {symbol}: {self._last_error()}")

        return True

    def get_rates(self, symbol: str, timeframe="1h", bars: int = 500):
        self._ensure_connected()
        self.ensure_symbol(symbol)

        tf = self._get_timeframe(timeframe)
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, bars)

        if rates is None:
            raise MT5ClientError(f"copy_rates_from_pos failed for {symbol}: {self._last_error()}")

        return [dict(r) for r in rates]

    # ------------------------------------------------------------------
    # Positions / orders
    # ------------------------------------------------------------------

    def positions(self, symbol: Optional[str] = None):
        self._ensure_connected()

        if symbol:
            positions = mt5.positions_get(symbol=symbol)
        else:
            positions = mt5.positions_get()

        if positions is None:
            raise MT5ClientError(f"positions_get failed: {self._last_error()}")

        return [p._asdict() for p in positions]

    def orders(self, symbol: Optional[str] = None):
        self._ensure_connected()

        if symbol:
            orders = mt5.orders_get(symbol=symbol)
        else:
            orders = mt5.orders_get()

        if orders is None:
            raise MT5ClientError(f"orders_get failed: {self._last_error()}")

        return [o._asdict() for o in orders]

    # ------------------------------------------------------------------
    # Trading
    # ------------------------------------------------------------------

    def market_order(
        self,
        symbol: str,
        volume: float,
        side: str,
        deviation: int = 20,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        comment: str = "leotrade",
        magic: int = 20260320,
    ):
        self._ensure_connected()
        self.ensure_symbol(symbol)

        side = side.upper()
        if side not in {"BUY", "SELL"}:
            raise MT5ClientError("side doit être BUY ou SELL")

        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            raise MT5ClientError(f"Tick introuvable pour {symbol}")

        order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
        price = tick.ask if side == "BUY" else tick.bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
            "price": price,
            "deviation": deviation,
            "magic": magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        if stop_loss is not None:
            request["sl"] = float(stop_loss)
        if take_profit is not None:
            request["tp"] = float(take_profit)

        result = mt5.order_send(request)
        if result is None:
            raise MT5ClientError(f"order_send failed: {self._last_error()}")

        result_dict = result._asdict()

        # retcode 10009/10008 souvent utilisés pour succès selon contexte
        if result_dict.get("retcode") not in {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED}:
            raise MT5ClientError(f"Échec market_order: {result_dict}")

        return result_dict

    def close_position(
        self,
        position_ticket: int,
        deviation: int = 20,
        comment: str = "leotrade-close",
        magic: int = 20260320,
    ):
        self._ensure_connected()

        positions = mt5.positions_get(ticket=position_ticket)
        if positions is None or len(positions) == 0:
            raise MT5ClientError(f"Position introuvable: {position_ticket}")

        pos = positions[0]
        symbol = pos.symbol
        volume = pos.volume

        self.ensure_symbol(symbol)

        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            raise MT5ClientError(f"Tick introuvable pour {symbol}")

        if pos.type == mt5.POSITION_TYPE_BUY:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        else:
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
            "position": position_ticket,
            "price": price,
            "deviation": deviation,
            "magic": magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result is None:
            raise MT5ClientError(f"close_position failed: {self._last_error()}")

        result_dict = result._asdict()
        if result_dict.get("retcode") not in {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED}:
            raise MT5ClientError(f"Échec close_position: {result_dict}")

        return result_dict
