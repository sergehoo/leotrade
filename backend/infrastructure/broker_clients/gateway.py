"""
Broker Gateway unifié.

Enveloppe tout client broker (Binance / MT5 / Deriv / futurs brokers) avec :

  - retry à backoff exponentiel — UNIQUEMENT sur les méthodes idempotentes
    (lectures). submit_order / cancel_order ne sont JAMAIS rejoués
    aveuglément : un retry réseau pourrait dupliquer un ordre réel.
  - circuit breaker par compte broker, persisté dans le cache partagé
    (Redis) : après N échecs consécutifs le circuit s'ouvre et toutes les
    requêtes échouent immédiatement pendant la fenêtre de refroidissement,
    protégeant la plateforme ET le broker des tempêtes de retries.
  - journalisation structurée de chaque échec pour le Centre Broker.

Usage :
    gateway = BrokerGateway(broker_account)
    balances = gateway.fetch_balances()
    gateway.submit_order(order)        # pas de retry, mais circuit + audit
"""

from __future__ import annotations

import logging
import time

from django.core.cache import cache

from core.retry import is_retryable_exception
from infrastructure.broker_clients import BrokerClientFactory

log = logging.getLogger("leotrade.brokers.gateway")


class CircuitOpenError(Exception):
    """Le circuit breaker du compte broker est ouvert — appel refusé."""


class CircuitStateUnavailableError(RuntimeError):
    """L'état Redis du circuit est indisponible avant une mutation broker."""

    retryable = False


class BrokerGateway:
    # Lectures sans effet de bord → retry sûr
    IDEMPOTENT_METHODS = frozenset({
        "test_connection",
        "fetch_balances",
        "fetch_positions",
        "fetch_open_orders",
        "fetch_order",
        "fetch_symbol_constraints",
    })
    # Mutations → jamais de retry automatique (risque de duplication d'ordre)
    MUTATING_METHODS = frozenset({"submit_order", "cancel_order", "close_position"})

    MAX_RETRIES = 3
    BASE_BACKOFF_SECONDS = 0.5

    FAILURE_THRESHOLD = 5      # échecs consécutifs avant ouverture du circuit
    OPEN_SECONDS = 60          # durée d'ouverture avant tentative half-open
    FAILURE_TTL = 300          # fenêtre de comptage des échecs

    def __init__(self, broker_account, client=None):
        self.broker_account = broker_account
        self._client = client

    def _get_client(self):
        if self._client is None:
            self._client = BrokerClientFactory.build(self.broker_account)
        return self._client

    # ------------------------------------------------------------------
    # Circuit breaker (état partagé entre workers via le cache Redis)
    # ------------------------------------------------------------------
    @property
    def _failures_key(self) -> str:
        return f"broker:cb:failures:{self.broker_account.pk}"

    @property
    def _open_key(self) -> str:
        return f"broker:cb:open:{self.broker_account.pk}"

    def circuit_state(self) -> str:
        """CLOSED | OPEN | HALF_OPEN | UNAVAILABLE."""
        try:
            if cache.get(self._open_key):
                return "OPEN"
            failures = cache.get(self._failures_key) or 0
            if failures >= self.FAILURE_THRESHOLD:
                return "HALF_OPEN"
            return "CLOSED"
        except Exception as exc:
            log.error(
                "gateway.circuit_state_unavailable broker_account_id=%s error=%s",
                self.broker_account.pk,
                exc,
            )
            return "UNAVAILABLE"

    def _record_failure(self, method: str, exc: Exception) -> None:
        try:
            failures = cache.get(self._failures_key) or 0
            failures += 1
            cache.set(self._failures_key, failures, timeout=self.FAILURE_TTL)
            if failures >= self.FAILURE_THRESHOLD:
                cache.set(self._open_key, True, timeout=self.OPEN_SECONDS)
                log.error(
                    "gateway.circuit_opened broker_account_id=%s broker=%s failures=%s last_error=%s",
                    self.broker_account.pk, self.broker_account.broker, failures, exc,
                )
                # Anomalie broker → notification critique au propriétaire
                # (dédupliquée : une par compte et par heure max).
                try:
                    from notifications.shortcuts import notify
                    notify(
                        self.broker_account.user, "BROKER_ERROR",
                        title=f"Broker injoignable : {self.broker_account.name}",
                        message=(
                            f"{failures} échecs consécutifs sur {self.broker_account.broker} "
                            f"« {self.broker_account.name} » — circuit breaker ouvert "
                            f"{self.OPEN_SECONDS}s. Dernière erreur : {str(exc)[:200]}"
                        ),
                        payload={"broker_account_id": self.broker_account.pk,
                                 "broker": self.broker_account.broker,
                                 "failures": failures},
                        dedupe_key=f"broker_circuit:{self.broker_account.pk}",
                    )
                except Exception:
                    pass
        except Exception:
            # Le cache ne doit jamais transformer une erreur broker en crash
            log.exception("gateway.circuit_record_failed")
        log.warning(
            "gateway.call_failed broker_account_id=%s broker=%s method=%s error=%s",
            self.broker_account.pk, self.broker_account.broker, method, exc,
        )

    def _record_success(self) -> None:
        try:
            cache.delete(self._failures_key)
            cache.delete(self._open_key)
        except Exception:
            pass

    def _is_circuit_open(self, *, fail_closed: bool) -> bool:
        try:
            return bool(cache.get(self._open_key))
        except Exception as exc:
            log.error(
                "gateway.circuit_cache_unavailable broker_account_id=%s "
                "broker=%s fail_closed=%s error=%s",
                self.broker_account.pk,
                self.broker_account.broker,
                fail_closed,
                exc,
            )
            if fail_closed:
                raise CircuitStateUnavailableError(
                    "État du circuit broker indisponible; mutation refusée avant envoi."
                ) from exc
            return False

    def _check_circuit(self, *, fail_closed: bool) -> None:
        if self._is_circuit_open(fail_closed=fail_closed):
            raise CircuitOpenError(
                f"Circuit breaker ouvert pour le compte broker "
                f"#{self.broker_account.pk} ({self.broker_account.broker}) — "
                f"réessai automatique d'ici {self.OPEN_SECONDS}s."
            )

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    def call(self, method: str, *args, **kwargs):
        if method in self.MUTATING_METHODS:
            return self._call_once(method, *args, **kwargs)
        if method in self.IDEMPOTENT_METHODS:
            return self._call_with_retry(method, *args, **kwargs)
        raise AttributeError(f"Méthode broker inconnue: {method}")

    def _call_once(self, method: str, *args, **kwargs):
        # Une mutation ne part jamais si l'état partagé du circuit est
        # indisponible. L'exception est levée AVANT l'appel broker, ce qui
        # permet à l'OMS de libérer le cash sans classer l'état comme ambigu.
        self._check_circuit(fail_closed=True)
        try:
            result = getattr(self._get_client(), method)(*args, **kwargs)
        except Exception as exc:
            self._record_failure(method, exc)
            raise
        self._record_success()
        return result

    def _call_with_retry(self, method: str, *args, **kwargs):
        # Une lecture reste autorisée pendant une panne Redis : elle ne peut
        # pas dupliquer un ordre et aide justement la réconciliation.
        self._check_circuit(fail_closed=False)
        last_exc: Exception | None = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                result = getattr(self._get_client(), method)(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                self._record_failure(method, exc)
                if (
                    not is_retryable_exception(exc)
                    or self._is_circuit_open(fail_closed=False)
                    or attempt == self.MAX_RETRIES
                ):
                    break
                time.sleep(self.BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)))
                continue
            self._record_success()
            return result
        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Interface BaseBrokerClient (mêmes signatures pour drop-in replacement)
    # ------------------------------------------------------------------
    def test_connection(self):
        return self.call("test_connection")

    def fetch_balances(self):
        return self.call("fetch_balances")

    def fetch_positions(self):
        return self.call("fetch_positions")

    def fetch_open_orders(self):
        return self.call("fetch_open_orders")

    def fetch_order(self, order):
        return self.call("fetch_order", order)

    def fetch_symbol_constraints(self, symbol: str):
        return self.call("fetch_symbol_constraints", symbol)

    def submit_order(self, order):
        return self.call("submit_order", order)

    def cancel_order(self, order):
        return self.call("cancel_order", order)

    def close_position(self, position, order):
        return self.call("close_position", position, order)
