"""
brokers/services/deriv_streamer.py
==================================

Worker WebSocket Deriv PERSISTANT (un par BrokerAccount actif).

Conçu pour tourner dans un process Daphne / asyncio dédié, supervisé par
systemd ou Kubernetes (readiness probe sur la connexion).

Subscriptions natives :
  - balance (push)
  - transaction (push)
  - proposal_open_contract (push, par contrat ouvert)

Reconnexion :
  - back-off exponentiel jusqu'à 60s ;
  - heartbeat via ping_interval=30s, ping_timeout=10s.

Idempotence :
  - tous les events sont routés vers brokers.services.deriv_sync.* qui sont
    déjà idempotents via BrokerExternalRef.

USAGE :
  python manage.py run_deriv_streamer

Ce module fournit aussi `start_for_account(account_id)` pour lancer un seul
streamer (utile en test).
"""

from __future__ import annotations

import asyncio
import json
import logging
from decimal import Decimal
from typing import Any

import websockets
from asgiref.sync import sync_to_async


log = logging.getLogger("lyneci.deriv.stream")


WS_URL_TEMPLATE = "wss://ws.binaryws.com/websockets/v3?app_id={app_id}"


class DerivStreamer:
    def __init__(self, broker_account_id: int, api_token: str, app_id: str):
        self.broker_account_id = broker_account_id
        self.api_token = api_token
        self.app_id = app_id
        self.ws: websockets.WebSocketClientProtocol | None = None
        self.req_seq = 0
        self._stop = asyncio.Event()

    async def run_forever(self) -> None:
        backoff = 1
        while not self._stop.is_set():
            try:
                await self._connect_and_loop()
                backoff = 1
            except Exception as exc:
                log.exception(
                    "deriv.stream.crashed broker_account_id=%s err=%s — retry in %ss",
                    self.broker_account_id, exc, backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _connect_and_loop(self) -> None:
        url = WS_URL_TEMPLATE.format(app_id=self.app_id)
        async with websockets.connect(
            url,
            ping_interval=30,
            ping_timeout=10,
            max_size=2_000_000,
        ) as ws:
            self.ws = ws
            log.info(
                "deriv.stream.connected broker_account_id=%s",
                self.broker_account_id,
            )

            await self._send({"authorize": self.api_token})
            await self._send({"balance": 1, "subscribe": 1})
            await self._send({"transaction": 1, "subscribe": 1})
            await self._send({"proposal_open_contract": 1, "subscribe": 1})

            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                await self._dispatch(msg)

    async def _send(self, payload: dict[str, Any]) -> None:
        assert self.ws is not None
        self.req_seq += 1
        payload["req_id"] = self.req_seq
        await self.ws.send(json.dumps(payload))

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        if "error" in msg and msg["error"]:
            log.warning(
                "deriv.stream.error broker_account_id=%s code=%s msg=%s",
                self.broker_account_id,
                msg["error"].get("code"),
                msg["error"].get("message"),
            )
            return

        msg_type = msg.get("msg_type")
        if msg_type == "balance":
            await sync_to_async(_safe_on_balance, thread_sensitive=False)(
                self.broker_account_id, msg.get("balance") or {}
            )
        elif msg_type == "transaction":
            await sync_to_async(_safe_on_transaction, thread_sensitive=False)(
                self.broker_account_id, msg.get("transaction") or {}
            )
        elif msg_type == "proposal_open_contract":
            await sync_to_async(_safe_on_open_contract, thread_sensitive=False)(
                self.broker_account_id, msg.get("proposal_open_contract") or {}
            )
        # autres types ignorés silencieusement

    def stop(self) -> None:
        self._stop.set()


def _safe_on_balance(broker_account_id: int, payload: dict) -> None:
    from brokers.services.deriv_sync import on_balance_update
    try:
        on_balance_update(broker_account_id=broker_account_id, payload=payload)
    except Exception as exc:  # pragma: no cover
        log.exception("on_balance_update.failed err=%s", exc)


def _safe_on_transaction(broker_account_id: int, payload: dict) -> None:
    from brokers.services.deriv_sync import on_transaction
    try:
        on_transaction(broker_account_id=broker_account_id, payload=payload)
    except Exception as exc:  # pragma: no cover
        log.exception("on_transaction.failed err=%s", exc)


def _safe_on_open_contract(broker_account_id: int, payload: dict) -> None:
    from brokers.services.deriv_sync import on_open_contract_update
    try:
        on_open_contract_update(broker_account_id=broker_account_id, payload=payload)
    except Exception as exc:  # pragma: no cover
        log.exception("on_open_contract_update.failed err=%s", exc)


# -----------------------------------------------------------------------------
# Entrypoints
# -----------------------------------------------------------------------------

async def start_for_account(broker_account_id: int) -> None:
    from brokers.models import BrokerAccount

    account = await sync_to_async(
        lambda: BrokerAccount.objects.filter(pk=broker_account_id).first(),
        thread_sensitive=False,
    )()
    if not account:
        log.error("start_for_account: BrokerAccount %s introuvable", broker_account_id)
        return

    token = await sync_to_async(lambda: account.deriv_token, thread_sensitive=False)()
    app_id = await sync_to_async(
        lambda: getattr(account, "deriv_app_id", None) or "1089",
        thread_sensitive=False,
    )()

    streamer = DerivStreamer(
        broker_account_id=broker_account_id,
        api_token=token,
        app_id=str(app_id),
    )
    await streamer.run_forever()


async def start_for_all_active_accounts() -> None:
    from brokers.models import BrokerAccount

    accounts = await sync_to_async(
        lambda: list(
            BrokerAccount.objects.filter(broker="DERIV", is_active=True).values_list("pk", flat=True)
        ),
        thread_sensitive=False,
    )()

    if not accounts:
        log.warning("start_for_all_active_accounts: aucun compte Deriv actif")
        return

    log.info("deriv.streamer.start n_accounts=%s", len(accounts))
    await asyncio.gather(*(start_for_account(pk) for pk in accounts))
