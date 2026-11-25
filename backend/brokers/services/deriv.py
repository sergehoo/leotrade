# /Users/ogahserge/Documents/leoTrade/brokers/services/deriv.py
from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx
import websocket


logger = logging.getLogger(__name__)


class DerivClientError(Exception):
    pass


class DerivClient:
    BASE_REST_URL = "https://api.derivws.com"
    PUBLIC_WS_URL = "wss://api.derivws.com/trading/v1/options/ws/public"

    def __init__(self, token: str, app_id: str):
        if not token:
            raise DerivClientError("Deriv token manquant.")
        if not app_id:
            raise DerivClientError("Deriv App ID / client_id manquant.")

        self.token = token
        self.app_id = app_id
        self.ws: websocket.WebSocket | None = None
        self.timeout = httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=10.0)
        self.http = httpx.Client(timeout=self.timeout, headers=self.rest_headers)

    @property
    def rest_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Deriv-App-ID": self.app_id,
        }

    def _rest_get(self, path: str) -> dict[str, Any]:
        url = f"{self.BASE_REST_URL}{path}"
        try:
            r = self.http.get(url)
            r.raise_for_status()
            return r.json()
        except httpx.ReadTimeout as exc:
            raise DerivClientError(f"GET {url} timed out") from exc
        except httpx.ConnectTimeout as exc:
            raise DerivClientError(f"GET {url} connection timed out") from exc
        except httpx.HTTPStatusError as exc:
            body = exc.response.text
            raise DerivClientError(
                f"GET {url} failed with {exc.response.status_code}: {body}"
            ) from exc
        except httpx.HTTPError as exc:
            raise DerivClientError(f"GET {url} failed: {exc}") from exc

    def _rest_post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.BASE_REST_URL}{path}"
        try:
            if payload is None:
                r = self.http.post(url)
            else:
                r = self.http.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json=payload,
                )

            r.raise_for_status()
            return r.json()

        except httpx.ReadTimeout as exc:
            raise DerivClientError(f"POST {url} timed out") from exc
        except httpx.ConnectTimeout as exc:
            raise DerivClientError(f"POST {url} connection timed out") from exc
        except httpx.HTTPStatusError as exc:
            body = exc.response.text
            raise DerivClientError(
                f"POST {url} failed with {exc.response.status_code}: {body}"
            ) from exc
        except httpx.HTTPError as exc:
            raise DerivClientError(f"POST {url} failed: {exc}") from exc
    def list_options_accounts(self) -> dict[str, Any]:
        return self._rest_get("/trading/v1/options/accounts")

    def get_otp_ws_url(self, account_id: str) -> str:
        data = self._rest_post(f"/trading/v1/options/accounts/{account_id}/otp")
        try:
            return data["data"]["url"]
        except KeyError as exc:
            raise DerivClientError(f"Réponse OTP inattendue: {data}") from exc

    def get_otp_ws_url_with_retry(
        self,
        account_id: str,
        *,
        retries: int = 3,
        sleep_seconds: float = 2.0,
    ) -> str:
        last_exc = None

        for attempt in range(1, retries + 1):
            try:
                return self.get_otp_ws_url(account_id)
            except DerivClientError as exc:
                last_exc = exc
                message = str(exc).lower()

                retryable = (
                    "timed out" in message
                    or "timeout" in message
                    or "connection timed out" in message
                )

                if not retryable or attempt >= retries:
                    break

                logger.warning(
                    "Deriv OTP retry %s/%s for account_id=%s because: %s",
                    attempt,
                    retries,
                    account_id,
                    exc,
                )
                time.sleep(sleep_seconds)

        raise last_exc or DerivClientError("Impossible d'obtenir l'OTP WebSocket.")

    def connect_with_otp_url(self, ws_url: str) -> None:
        try:
            self.ws = websocket.create_connection(ws_url, timeout=20)
        except Exception as exc:
            raise DerivClientError(f"Connexion WebSocket Deriv impossible: {exc}") from exc

    def connect_public(self) -> None:
        try:
            self.ws = websocket.create_connection(self.PUBLIC_WS_URL, timeout=20)
        except Exception as exc:
            raise DerivClientError(f"Connexion WebSocket publique Deriv impossible: {exc}") from exc

    def close(self) -> None:
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None

        try:
            self.http.close()
        except Exception:
            pass

    def _send(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.ws:
            raise DerivClientError("WebSocket Deriv non connecté.")

        try:
            logger.warning("DERIV_WS_PAYLOAD=%s", payload)
            self.ws.send(json.dumps(payload))
            raw = self.ws.recv()
            data = json.loads(raw)
        except websocket.WebSocketTimeoutException as exc:
            raise DerivClientError("Timeout WebSocket Deriv.") from exc
        except Exception as exc:
            raise DerivClientError(f"Erreur WebSocket Deriv: {exc}") from exc

        if data.get("error"):
            message = data["error"].get("message", "Erreur Deriv inconnue")
            code = data["error"].get("code", "")
            raise DerivClientError(f"{code}: {message}" if code else message)

        return data

    def ping(self) -> dict[str, Any]:
        return self._send({"ping": 1})

    def active_symbols(self, contract_type: list[str] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"active_symbols": "brief"}
        if contract_type:
            payload["contract_type"] = contract_type
        return self._send(payload)

    def contracts_for(self, symbol: str) -> dict[str, Any]:
        return self._send({"contracts_for": symbol})

    def proposal(
            self,
            *,
            symbol: str,
            amount: float,
            contract_type: str,
            currency: str = "USD",
            duration: int | None = 5,
            duration_unit: str | None = "t",
            basis: str = "stake",
            multiplier: int | None = None,
            underlying_symbol: str | None = None,
    ) -> dict[str, Any]:
        resolved_symbol = symbol or underlying_symbol

        if not resolved_symbol:
            raise DerivClientError("proposal() : symbole manquant.")

        payload: dict[str, Any] = {
            "proposal": 1,
            "amount": amount,
            "basis": basis,
            "contract_type": contract_type,
            "currency": currency,

            # IMPORTANT :
            # Sur ton endpoint Deriv actuel :
            # wss://api.derivws.com/trading/v1/options/ws/...
            # la clé attendue est underlying, pas symbol.
            "underlying_symbol": resolved_symbol,
        }

        is_multiplier_contract = str(contract_type).upper() in {"MULTUP", "MULTDOWN"}

        if multiplier is not None:
            payload["multiplier"] = multiplier

        if not is_multiplier_contract:
            if duration is not None:
                payload["duration"] = duration

            if duration_unit is not None:
                payload["duration_unit"] = duration_unit

        return self._send(payload)

    def buy(self, *, proposal_id: str, price: float) -> dict[str, Any]:
        return self._send({
            "buy": proposal_id,
            "price": price,
        })

    def proposal_open_contract(self, *, contract_id: int | str) -> dict[str, Any]:
        return self._send({
            "proposal_open_contract": 1,
            "contract_id": int(contract_id),
        })

    def portfolio_ws(self) -> dict[str, Any]:
        return self._send({"portfolio": 1})

    def balance_ws(self, subscribe: int = 0) -> dict[str, Any]:
        payload: dict[str, Any] = {"balance": 1}
        if subscribe:
            payload["subscribe"] = subscribe
        return self._send(payload)

    def ticks_history(self, symbol: str, count: int = 1000, end: str = "latest", start: int | None = None):
        payload = {
            "ticks_history": symbol,
            "style": "candles",
            "count": count,
            "end": end,
        }
        if start is not None:
            payload["start"] = start
        return self._send(payload)

    def candles(self, symbol: str, granularity: int, count: int = 300):
        return self._send({
            "ticks_history": symbol,
            "style": "candles",
            "granularity": granularity,
            "count": count,
            "end": "latest",
        })