# /Users/ogahserge/Documents/leoTrade/brokers/services/binance.py
import time
import hmac
import hashlib
from decimal import Decimal
from typing import Any, Optional
from urllib.parse import urlencode

import httpx


class BinanceAPIError(Exception):
    pass


class BinanceRateLimitError(BinanceAPIError):
    """429 — Rate limit Binance. Contient le délai suggéré."""
    def __init__(self, message: str, retry_after: int = 5):
        super().__init__(message)
        self.retry_after = retry_after


class BinanceClient:
    BASE_URL = "https://api.binance.com"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
        recv_window: int = 5000,
    ):
        self.api_key = api_key
        self.api_secret = api_secret.encode()
        self.base_url = base_url or self.BASE_URL
        self.timeout = timeout
        self.recv_window = recv_window

        self.client = httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={
                "X-MBX-APIKEY": self.api_key,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _timestamp(self) -> int:
        return int(time.time() * 1000)

    def _sign(self, params: dict[str, Any]) -> str:
        query = urlencode(params, doseq=True)
        return hmac.new(self.api_secret, query.encode(), hashlib.sha256).hexdigest()

    def _signed_params(self, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        params = params.copy() if params else {}
        params["timestamp"] = self._timestamp()
        params["recvWindow"] = self.recv_window
        params["signature"] = self._sign(params)
        return params

    def _handle_response(self, response: httpx.Response) -> Any:
        # Rate limit Binance : 429 → attendre et réessayer (max 3 tentatives)
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", "5"))
            retry_after = max(1, min(retry_after, 60))
            raise BinanceRateLimitError(
                f"Rate limit Binance (429). Réessayer dans {retry_after}s.",
                retry_after=retry_after,
            )
        # Banissement temporaire Binance (418)
        if response.status_code == 418:
            raise BinanceAPIError("IP bannie temporairement par Binance (418). Réduire la fréquence des requêtes.")

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            try:
                payload = response.json()
                msg = payload.get("msg", str(exc))
                code = payload.get("code")
                raise BinanceAPIError(f"Binance API error {code}: {msg}") from exc
            except BinanceAPIError:
                raise
            except Exception:
                raise BinanceAPIError(f"Binance HTTP error: {response.text}") from exc

        try:
            return response.json()
        except Exception as exc:
            raise BinanceAPIError("Réponse Binance non JSON.") from exc

    def _request_with_retry(self, method: str, path: str, max_retries: int = 3, **kwargs) -> Any:
        """Exécute une requête HTTP avec retry automatique sur 429 (rate limit)."""
        for attempt in range(max_retries):
            try:
                fn = getattr(self.client, method)
                response = fn(path, **kwargs)
                return self._handle_response(response)
            except BinanceRateLimitError as e:
                if attempt < max_retries - 1:
                    wait = e.retry_after * (2 ** attempt)  # backoff exponentiel
                    time.sleep(min(wait, 60))
                else:
                    raise

    # ------------------------------------------------------------------
    # PUBLIC / MARKET DATA
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        r = self.client.get("/api/v3/ping")
        self._handle_response(r)
        return True

    def server_time(self) -> dict[str, Any]:
        r = self.client.get("/api/v3/time")
        return self._handle_response(r)

    def exchange_info(self, symbol: Optional[str] = None) -> dict[str, Any]:
        params = {"symbol": symbol} if symbol else {}
        r = self.client.get("/api/v3/exchangeInfo", params=params)
        return self._handle_response(r)

    def symbol_price(self, symbol: str) -> dict[str, Any]:
        r = self.client.get("/api/v3/ticker/price", params={"symbol": symbol.upper()})
        return self._handle_response(r)

    def ticker_24h(self, symbol: str) -> dict[str, Any]:
        r = self.client.get("/api/v3/ticker/24hr", params={"symbol": symbol.upper()})
        return self._handle_response(r)

    def klines(self, symbol: str, interval: str = "1h", limit: int = 500) -> list[list[Any]]:
        r = self.client.get(
            "/api/v3/klines",
            params={
                "symbol": symbol.upper(),
                "interval": interval,
                "limit": limit,
            },
        )
        return self._handle_response(r)

    # ------------------------------------------------------------------
    # PRIVATE / ACCOUNT
    # ------------------------------------------------------------------

    def account_info(self) -> dict[str, Any]:
        params = self._signed_params()
        r = self.client.get("/api/v3/account", params=params)
        return self._handle_response(r)

    def test_connection(self) -> tuple[bool, str]:
        try:
            self.ping()
            self.account_info()
            return True, ""
        except Exception as exc:
            return False, str(exc)

    def balances(self, non_zero_only: bool = True) -> list[dict[str, Any]]:
        info = self.account_info()
        balances = info.get("balances", [])

        if not non_zero_only:
            return balances

        filtered = []
        for item in balances:
            free = Decimal(item.get("free", "0"))
            locked = Decimal(item.get("locked", "0"))
            if free > 0 or locked > 0:
                filtered.append(item)
        return filtered

    def asset_balance(self, asset: str) -> Optional[dict[str, Any]]:
        asset = asset.upper()
        for item in self.account_info().get("balances", []):
            if item.get("asset") == asset:
                return item
        return None

    # ------------------------------------------------------------------
    # PRIVATE / TRADING
    # ------------------------------------------------------------------

    def create_market_order(self, symbol: str, side: str, quantity: float) -> dict[str, Any]:
        side = side.upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("side doit être BUY ou SELL")

        params = self._signed_params({
            "symbol": symbol.upper(),
            "side": side,
            "type": "MARKET",
            "quantity": quantity,
        })

        r = self.client.post("/api/v3/order", params=params)
        return self._handle_response(r)

    def create_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        time_in_force: str = "GTC",
    ) -> dict[str, Any]:
        side = side.upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("side doit être BUY ou SELL")

        params = self._signed_params({
            "symbol": symbol.upper(),
            "side": side,
            "type": "LIMIT",
            "timeInForce": time_in_force,
            "quantity": quantity,
            "price": price,
        })

        r = self.client.post("/api/v3/order", params=params)
        return self._handle_response(r)

    def order_status(self, symbol: str, order_id: int) -> dict[str, Any]:
        params = self._signed_params({
            "symbol": symbol.upper(),
            "orderId": order_id,
        })
        r = self.client.get("/api/v3/order", params=params)
        return self._handle_response(r)

    def cancel_order(self, symbol: str, order_id: int) -> dict[str, Any]:
        params = self._signed_params({
            "symbol": symbol.upper(),
            "orderId": order_id,
        })
        r = self.client.delete("/api/v3/order", params=params)
        return self._handle_response(r)

    def open_orders(self, symbol: Optional[str] = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol.upper()

        params = self._signed_params(params)
        r = self.client.get("/api/v3/openOrders", params=params)
        return self._handle_response(r)