"""
Phase Broker Gateway — retry, circuit breaker, health, Centre Broker.

Couverture :
  1. Les lectures (fetch_balances...) sont rejouées avec backoff puis
     réussissent ; les mutations (submit_order) ne sont JAMAIS rejouées.
  2. Le circuit s'ouvre après FAILURE_THRESHOLD échecs consécutifs, refuse
     immédiatement les appels (CircuitOpenError), puis se referme sur succès.
  3. L'endpoint Centre Broker /brokers/health/api/ expose l'état réel.
  4. La tâche de health check persiste le statut sur BrokerAccount.
"""

from unittest import mock

import pytest
from django.core.cache import cache
from django.urls import reverse

from infrastructure.broker_clients.gateway import BrokerGateway, CircuitOpenError


class FlakyClient:
    """Échoue n fois puis réussit — pour tester le retry."""

    def __init__(self, failures_before_success: int):
        self.remaining_failures = failures_before_success
        self.calls = 0

    def _maybe_fail(self):
        self.calls += 1
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            raise ConnectionError("boom")
        return {"ok": True}

    def test_connection(self):
        return self._maybe_fail()

    def fetch_balances(self):
        return self._maybe_fail()

    def submit_order(self, order):
        return self._maybe_fail()


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def gateway(broker_paper):
    def _build(client):
        return BrokerGateway(broker_paper, client=client)
    return _build


# ─────────────────────────────────────────────────────────────────────────────
#  1. Retry
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_idempotent_method_retries_then_succeeds(gateway):
    client = FlakyClient(failures_before_success=2)
    gw = gateway(client)
    gw.BASE_BACKOFF_SECONDS = 0  # pas d'attente réelle en test

    with mock.patch("infrastructure.broker_clients.gateway.time.sleep"):
        result = gw.fetch_balances()

    assert result == {"ok": True}
    assert client.calls == 3  # 2 échecs + 1 succès


@pytest.mark.django_db
def test_mutating_method_never_retried(gateway):
    client = FlakyClient(failures_before_success=1)
    gw = gateway(client)

    with pytest.raises(ConnectionError):
        gw.submit_order(order=object())

    assert client.calls == 1  # un seul essai, pas de duplication d'ordre


@pytest.mark.django_db
def test_retry_exhaustion_raises_last_error(gateway):
    client = FlakyClient(failures_before_success=99)
    gw = gateway(client)

    with mock.patch("infrastructure.broker_clients.gateway.time.sleep"):
        with pytest.raises(ConnectionError):
            gw.fetch_balances()

    assert client.calls == gw.MAX_RETRIES


# ─────────────────────────────────────────────────────────────────────────────
#  2. Circuit breaker
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_circuit_opens_after_threshold(gateway):
    client = FlakyClient(failures_before_success=99)
    gw = gateway(client)

    with mock.patch("infrastructure.broker_clients.gateway.time.sleep"):
        # Chaque appel fait MAX_RETRIES tentatives → 2 appels suffisent
        # à dépasser FAILURE_THRESHOLD (5).
        with pytest.raises(ConnectionError):
            gw.fetch_balances()
        with pytest.raises((ConnectionError, CircuitOpenError)):
            gw.fetch_balances()

    assert gw.circuit_state() == "OPEN"

    # Circuit ouvert → refus immédiat sans toucher le client
    calls_before = client.calls
    with pytest.raises(CircuitOpenError):
        gw.fetch_balances()
    assert client.calls == calls_before


@pytest.mark.django_db
def test_circuit_closes_on_success(gateway):
    client = FlakyClient(failures_before_success=0)
    gw = gateway(client)

    # Simule un circuit semi-ouvert : échecs comptés mais fenêtre OPEN expirée
    cache.set(gw._failures_key, gw.FAILURE_THRESHOLD, timeout=300)
    assert gw.circuit_state() == "HALF_OPEN"

    gw.fetch_balances()

    assert gw.circuit_state() == "CLOSED"


@pytest.mark.django_db
def test_mutating_call_blocked_when_circuit_open(gateway):
    client = FlakyClient(failures_before_success=0)
    gw = gateway(client)
    cache.set(gw._open_key, True, timeout=60)

    with pytest.raises(CircuitOpenError):
        gw.submit_order(order=object())

    assert client.calls == 0


# ─────────────────────────────────────────────────────────────────────────────
#  3. Centre Broker API
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_broker_health_api(client, user, broker_paper):
    client.force_login(user)

    resp = client.get(reverse("broker-health-api"))

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["count"] == 1
    account = payload["accounts"][0]
    assert account["broker"] == "DERIV"
    assert account["circuit_state"] == "CLOSED"
    assert "connected" in account and "last_error" in account


# ─────────────────────────────────────────────────────────────────────────────
#  4. Health check task
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_health_check_task_persists_status(broker_paper):
    from brokers.tasks import check_all_brokers_health_task

    with mock.patch(
        "infrastructure.broker_clients.gateway.BrokerClientFactory.build",
        return_value=FlakyClient(failures_before_success=0),
    ):
        result = check_all_brokers_health_task()

    assert result == {"checked": 1, "healthy": 1}
    broker_paper.refresh_from_db()
    assert broker_paper.last_connection_status is True
    assert broker_paper.status == "ACTIVE"
    assert broker_paper.last_connected_at is not None


@pytest.mark.django_db
def test_health_check_task_records_failure(broker_paper):
    from brokers.tasks import check_all_brokers_health_task

    with mock.patch(
        "infrastructure.broker_clients.gateway.BrokerClientFactory.build",
        return_value=FlakyClient(failures_before_success=99),
    ), mock.patch("infrastructure.broker_clients.gateway.time.sleep"):
        result = check_all_brokers_health_task()

    assert result == {"checked": 1, "healthy": 0}
    broker_paper.refresh_from_db()
    assert broker_paper.last_connection_status is False
    assert broker_paper.status == "ERROR"
    assert "boom" in broker_paper.last_connection_error
