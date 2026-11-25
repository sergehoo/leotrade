"""
brokers/tasks_deriv_sync.py
===========================

Tâches Celery de FALLBACK pour la synchronisation Deriv.

Le mode normal est le worker WS persistant (deriv_streamer.py). Si le stream
tombe ou que la machine n'a pas de Daphne, ces tâches assurent une
synchronisation polled avec les mêmes handlers idempotents.

Toutes les tâches :
- prennent un Redis lock pour éviter les chevauchements ;
- loguent en JSON structuré ;
- échouent silencieusement (les erreurs sont remontées à Sentry, pas en exception
  Celery, pour ne pas bloquer le beat).
"""

from __future__ import annotations

import logging
from decimal import Decimal

from celery import shared_task

from brokers.models import BrokerAccount
from brokers.services.deriv_sync import (
    on_balance_update,
    on_open_contract_update,
)


log = logging.getLogger("lyneci.deriv.tasks")


def _redis_lock(name: str, ttl_seconds: int = 50):
    """
    Lock simple sur Redis (utilisé par django-redis ou celery backend).
    Si Redis n'est pas dispo (test runner), on retourne un context manager noop.
    """
    try:
        from django.core.cache import cache
        return cache.lock(name, timeout=ttl_seconds, blocking_timeout=0)
    except Exception:
        from contextlib import nullcontext
        return nullcontext()


def _iter_active_deriv_accounts():
    qs = BrokerAccount.objects.filter(
        broker="DERIV",
        is_active=True,
    )
    yield from qs


# -----------------------------------------------------------------------------
# 1. Sync balance — toutes les 60s
# -----------------------------------------------------------------------------

@shared_task(name="brokers.tasks_deriv_sync.sync_deriv_balance_task", bind=True)
def sync_deriv_balance_task(self):
    """
    Pour chaque BrokerAccount Deriv actif :
      - se connecte WS,
      - appelle balance_ws(),
      - délègue à on_balance_update().
    """
    with _redis_lock("lock:sync_deriv_balance_task", ttl_seconds=55):
        n_ok, n_err = 0, 0
        for account in _iter_active_deriv_accounts():
            try:
                _sync_balance_for_account(account)
                n_ok += 1
            except Exception as exc:
                n_err += 1
                log.exception(
                    "sync_deriv_balance_task.failed broker_account_id=%s err=%s",
                    account.id, exc,
                )
        log.info("sync_deriv_balance_task.done ok=%s err=%s", n_ok, n_err)
        return {"ok": n_ok, "err": n_err}


def _sync_balance_for_account(account: BrokerAccount) -> None:
    from brokers.services.deriv import DerivClient  # import local
    from brokers.services_connection import build_deriv_client_for_account  # voir patch

    client: DerivClient | None = build_deriv_client_for_account(account)
    if client is None:
        log.warning("sync_balance: pas de client buildable pour account_id=%s", account.id)
        return

    try:
        # Connexion publique suffit pour balance? NON, il faut auth.
        # On utilise le flux OTP-WS (privé).
        accounts = client.list_options_accounts()
        deriv_account_id = (
            (accounts.get("data") or [{}])[0].get("id")
            if isinstance(accounts.get("data"), list)
            else None
        )
        if not deriv_account_id:
            log.warning("sync_balance: pas d'account Deriv pour broker_account_id=%s", account.id)
            return

        ws_url = client.get_otp_ws_url_with_retry(deriv_account_id)
        client.connect_with_otp_url(ws_url)
        client._send({"authorize": client.token})
        bal = client.balance_ws(subscribe=0)

        balance_payload = bal.get("balance") or {}
        on_balance_update(broker_account_id=account.id, payload=balance_payload)
    finally:
        client.close()


# -----------------------------------------------------------------------------
# 2. Sync open positions — toutes les 60s
# -----------------------------------------------------------------------------

@shared_task(name="brokers.tasks_deriv_sync.sync_deriv_positions_task", bind=True)
def sync_deriv_positions_task(self):
    with _redis_lock("lock:sync_deriv_positions_task", ttl_seconds=55):
        n_ok, n_err, total_contracts = 0, 0, 0
        for account in _iter_active_deriv_accounts():
            try:
                count = _sync_positions_for_account(account)
                total_contracts += count
                n_ok += 1
            except Exception as exc:
                n_err += 1
                log.exception(
                    "sync_deriv_positions_task.failed broker_account_id=%s err=%s",
                    account.id, exc,
                )
        log.info(
            "sync_deriv_positions_task.done accounts_ok=%s err=%s contracts_synced=%s",
            n_ok, n_err, total_contracts,
        )
        return {"ok": n_ok, "err": n_err, "contracts": total_contracts}


def _sync_positions_for_account(account: BrokerAccount) -> int:
    """
    Récupère les contrats ouverts via portfolio_ws() puis détaille
    chaque contrat via proposal_open_contract().
    """
    from brokers.services.deriv import DerivClient
    from brokers.services_connection import build_deriv_client_for_account

    client: DerivClient | None = build_deriv_client_for_account(account)
    if client is None:
        return 0

    count = 0
    try:
        accounts = client.list_options_accounts()
        deriv_account_id = (
            (accounts.get("data") or [{}])[0].get("id")
            if isinstance(accounts.get("data"), list)
            else None
        )
        if not deriv_account_id:
            return 0

        ws_url = client.get_otp_ws_url_with_retry(deriv_account_id)
        client.connect_with_otp_url(ws_url)
        client._send({"authorize": client.token})

        # Liste des contrats ouverts
        portfolio_resp = client.portfolio_ws()
        contracts = (portfolio_resp.get("portfolio") or {}).get("contracts") or []

        for c in contracts:
            contract_id = c.get("contract_id")
            if not contract_id:
                continue
            try:
                detail = client.proposal_open_contract(contract_id=contract_id)
                payload = detail.get("proposal_open_contract") or {}
                on_open_contract_update(
                    broker_account_id=account.id,
                    payload=payload,
                )
                count += 1
            except Exception as exc:
                log.warning(
                    "sync_positions: échec sur contract_id=%s err=%s",
                    contract_id, exc,
                )
    finally:
        client.close()

    return count


# -----------------------------------------------------------------------------
# 3. Sync UN contrat précis (à la demande, après création)
# -----------------------------------------------------------------------------

@shared_task(name="brokers.tasks_deriv_sync.sync_single_deriv_contract_task")
def sync_single_deriv_contract_task(broker_account_id: int, contract_id: str):
    """
    Synchronisation à la demande d'un contrat précis. Appelé après la création
    d'un ordre Deriv pour confirmer qu'il est bien ouvert/clos côté broker.
    """
    from brokers.services.deriv import DerivClient
    from brokers.services_connection import build_deriv_client_for_account

    account = BrokerAccount.objects.filter(pk=broker_account_id).first()
    if not account:
        return None

    client: DerivClient | None = build_deriv_client_for_account(account)
    if client is None:
        return None

    try:
        accounts = client.list_options_accounts()
        deriv_account_id = (
            (accounts.get("data") or [{}])[0].get("id")
            if isinstance(accounts.get("data"), list)
            else None
        )
        if not deriv_account_id:
            return None

        ws_url = client.get_otp_ws_url_with_retry(deriv_account_id)
        client.connect_with_otp_url(ws_url)
        client._send({"authorize": client.token})

        detail = client.proposal_open_contract(contract_id=contract_id)
        payload = detail.get("proposal_open_contract") or {}
        on_open_contract_update(
            broker_account_id=account.id,
            payload=payload,
        )
        return {"ok": True, "contract_id": str(contract_id), "status": payload.get("status")}
    except Exception as exc:
        log.exception(
            "sync_single_deriv_contract_task.failed account_id=%s contract_id=%s err=%s",
            broker_account_id, contract_id, exc,
        )
        return {"ok": False, "error": str(exc)}
    finally:
        client.close()
