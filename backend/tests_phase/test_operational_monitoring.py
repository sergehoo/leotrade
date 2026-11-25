from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest import mock

import pytest
import yaml
from django.core.cache import cache
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone


PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Monorepo : artefacts d'infra sous infrastructure/ (cf. test_production_readiness).
INFRA_ROOT = PROJECT_ROOT.parent / "infrastructure"


def _snapshot(*, generated_at_epoch: int, **values) -> dict:
    defaults = {
        "live_orders_unknown": 0,
        "live_orders_unknown_beyond_slo": 0,
        "live_orders_stale_submitting": 0,
        "live_portfolios_reconciliation_stale": 0,
        "live_brokers_unhealthy": 0,
        "outbox_pending": 0,
        "outbox_processing": 0,
        "outbox_dead": 0,
        "outbox_oldest_pending_age_seconds": 0,
        "outbox_lag_beyond_slo": 0,
        "active_kill_switches": 0,
    }
    defaults.update(values)
    return {
        "schema_version": 1,
        "generated_at": timezone.now().isoformat(),
        "generated_at_epoch": generated_at_epoch,
        "status": "healthy",
        "values": defaults,
        "thresholds": {},
    }


@pytest.fixture(autouse=True)
def clear_monitoring_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_operational_snapshot_detects_live_execution_failures(
    user,
    broker_live,
    portfolio_live,
    risk_profile_live,
):
    from core.models import OutboxEvent
    from core.monitoring import collect_operational_snapshot
    from execution.models import Order
    from risk.models import KillSwitchEvent

    now = timezone.now()
    old = now - timedelta(minutes=20)
    broker_live.last_connection_status = False
    broker_live.last_connected_at = old
    broker_live.status = "ERROR"
    broker_live.save(update_fields=[
        "last_connection_status",
        "last_connected_at",
        "status",
        "updated_at",
    ])
    broker_live.__class__.objects.filter(pk=broker_live.pk).update(created_at=old)
    portfolio_live.__class__.objects.filter(pk=portfolio_live.pk).update(created_at=old)

    order = Order.objects.create(
        user=user,
        portfolio=portfolio_live,
        broker_account=broker_live,
        symbol="R_100",
        side="BUY",
        order_type="MARKET",
        mode="LIVE",
        status="UNKNOWN_BROKER_STATE",
        requested_quantity=Decimal("1"),
        approved_quantity=Decimal("1"),
        requested_stake_amount=Decimal("10.00"),
        approved_notional=Decimal("10.00"),
        requested_price=Decimal("10.00"),
        idempotency_key="monitoring-unknown-order",
    )
    Order.objects.filter(pk=order.pk).update(updated_at=old)
    OutboxEvent.objects.create(
        topic="monitoring.dead",
        aggregate_type="test",
        aggregate_id="1",
        status="DEAD",
    )
    KillSwitchEvent.objects.create(
        portfolio=portfolio_live,
        risk_profile=risk_profile_live,
        reason_code="MONITORING_TEST",
        reason="test",
    )

    snapshot = collect_operational_snapshot(now=now)

    assert snapshot["status"] == "critical"
    assert snapshot["values"]["live_orders_unknown"] == 1
    assert snapshot["values"]["live_orders_unknown_beyond_slo"] == 1
    assert snapshot["values"]["live_portfolios_reconciliation_stale"] == 1
    assert snapshot["values"]["live_brokers_unhealthy"] == 1
    assert snapshot["values"]["outbox_dead"] == 1
    assert snapshot["values"]["active_kill_switches"] == 1


@pytest.mark.django_db
def test_collector_task_persists_heartbeat_and_queues_alert_dispatch():
    from core.monitoring import read_operational_snapshot
    from core.tasks import collect_operational_snapshot_task

    with mock.patch(
        "core.tasks.dispatch_operational_alerts_task.delay"
    ) as dispatch:
        result = collect_operational_snapshot_task()

    assert result["status"] == "healthy"
    assert read_operational_snapshot()["generated_at_epoch"] == result["generated_at_epoch"]
    dispatch.assert_called_once_with(result)


@pytest.mark.django_db
@override_settings(
    HEALTH_REQUIRE_MONITORING_HEARTBEAT=True,
    MONITORING_HEARTBEAT_MAX_AGE_SECONDS=120,
)
def test_readiness_requires_a_recent_worker_heartbeat(client):
    from core.monitoring import store_operational_snapshot

    response = client.get(reverse("health_ready"))
    assert response.status_code == 503
    assert response.json()["checks"]["monitoring_heartbeat"] is False

    now_epoch = int(timezone.now().timestamp())
    store_operational_snapshot(_snapshot(generated_at_epoch=now_epoch))
    response = client.get(reverse("health_ready"))
    assert response.status_code == 200
    assert response.json()["checks"]["monitoring_heartbeat"] is True

    store_operational_snapshot(_snapshot(generated_at_epoch=now_epoch - 121))
    response = client.get(reverse("health_ready"))
    assert response.status_code == 503


@pytest.mark.django_db
def test_diagnostics_endpoint_is_staff_only(client, user):
    from core.monitoring import store_operational_snapshot

    store_operational_snapshot(
        _snapshot(generated_at_epoch=int(timezone.now().timestamp()))
    )

    response = client.get(reverse("health_diagnostics"))
    assert response.status_code == 403

    client.force_login(user)
    response = client.get(reverse("health_diagnostics"))
    assert response.status_code == 403

    user.is_staff = True
    user.save(update_fields=["is_staff"])
    response = client.get(reverse("health_diagnostics"))
    assert response.status_code == 200
    assert response.json()["snapshot"]["schema_version"] == 1


@override_settings(MONITORING_ALERT_REPEAT_SECONDS=900)
def test_operational_alerts_are_deduplicated_and_emit_recovery():
    from core.monitoring import dispatch_operational_alerts

    active = _snapshot(generated_at_epoch=1_000, outbox_dead=1)
    quiet = _snapshot(generated_at_epoch=1_060, outbox_dead=1)
    recovered = _snapshot(generated_at_epoch=1_061)

    with mock.patch("core.alerting.send_alert", return_value={}) as send_alert:
        first = dispatch_operational_alerts(active)
        second = dispatch_operational_alerts(quiet)
        third = dispatch_operational_alerts(recovered)

    assert first == {"sent": 1, "recovered": 0, "suppressed": 0, "active": 1}
    assert second == {"sent": 0, "recovered": 0, "suppressed": 1, "active": 1}
    assert third == {"sent": 0, "recovered": 1, "suppressed": 0, "active": 0}
    assert send_alert.call_count == 2
    assert send_alert.call_args_list[1].kwargs["title"].startswith("Rétablissement")


def test_operational_alert_failure_is_retryable():
    from core.monitoring import (
        OperationalAlertDeliveryError,
        dispatch_operational_alerts,
    )

    active = _snapshot(generated_at_epoch=1_000, outbox_dead=1)
    with mock.patch(
        "core.alerting.send_alert",
        return_value={"email": False, "webhook": False},
    ), pytest.raises(OperationalAlertDeliveryError):
        dispatch_operational_alerts(active)


def test_prometheus_collector_exposes_trading_metrics():
    from core.metrics import OperationalMetricsCollector
    from core.monitoring import store_operational_snapshot

    store_operational_snapshot(
        _snapshot(
            generated_at_epoch=int(timezone.now().timestamp()),
            live_orders_unknown=2,
            outbox_dead=1,
        )
    )

    metrics = list(OperationalMetricsCollector().collect())
    samples = {
        sample.name: sample.value
        for metric in metrics
        for sample in metric.samples
    }
    assert samples["lyneci_operational_snapshot_available"] == 1
    assert samples["lyneci_live_orders_unknown"] == 2
    assert samples['lyneci_outbox_events'] == 1


@pytest.mark.django_db
@override_settings(METRICS_AUTH_TOKEN="metrics-test-token")
def test_prometheus_endpoint_publishes_operational_metrics(client):
    from core.monitoring import store_operational_snapshot

    store_operational_snapshot(
        _snapshot(
            generated_at_epoch=int(timezone.now().timestamp()),
            live_orders_unknown=3,
        )
    )

    response = client.get("/metrics", HTTP_AUTHORIZATION="Bearer metrics-test-token")
    assert response.status_code == 200
    assert b"lyneci_live_orders_unknown 3.0" in response.content


@pytest.mark.django_db
def test_system_diagnostics_supports_fresh_machine_readable_output():
    output = StringIO()

    call_command("system_diagnostics", fresh=True, json=True, stdout=output)

    payload = yaml.safe_load(output.getvalue())
    assert payload["status"] == "ok"
    assert payload["checks"] == {
        "database": True,
        "cache": True,
        "monitoring": True,
    }


def test_deployment_enforces_flower_auth_and_declares_alert_rules():
    compose = (INFRA_ROOT / "docker" / "docker-compose.yml").read_text()
    requirements = (PROJECT_ROOT / "requirements.txt").read_text()
    alert_rules = yaml.safe_load(
        (INFRA_ROOT / "deploy/observability/lyneci-alerts.yml").read_text()
    )

    assert "flower==2.0.1" in requirements
    assert 'test -n "$$FLOWER_BASIC_AUTH"' in compose
    assert "worker@$$HOSTNAME" in compose
    assert "celerybeat.pid" in compose
    alerts = alert_rules["groups"][0]["rules"]
    assert {rule["alert"] for rule in alerts} >= {
        "LyneciOperationalSnapshotMissing",
        "LyneciUnknownLiveOrder",
        "LyneciOutboxDeadLetter",
    }
