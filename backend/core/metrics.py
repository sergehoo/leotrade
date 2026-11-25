from __future__ import annotations

import logging

from django.utils import timezone
from prometheus_client import REGISTRY
from prometheus_client.core import GaugeMetricFamily

from core.monitoring import operational_snapshot_age, read_operational_snapshot


logger = logging.getLogger("leotrade.monitoring")
_registered = False


class OperationalMetricsCollector:
    def collect(self):
        snapshot = read_operational_snapshot()
        available = GaugeMetricFamily(
            "leotrade_operational_snapshot_available",
            "Whether a recent LeoTrade operational snapshot is available.",
        )
        available.add_metric([], 1 if snapshot else 0)
        yield available

        if not snapshot:
            return

        values = snapshot.get("values") or {}
        age = GaugeMetricFamily(
            "leotrade_operational_snapshot_age_seconds",
            "Age of the latest LeoTrade operational snapshot.",
        )
        age.add_metric([], operational_snapshot_age(snapshot, now=timezone.now()) or 0)
        yield age

        status_metric = GaugeMetricFamily(
            "leotrade_operational_status",
            "Current operational status as a one-hot gauge.",
            labels=["status"],
        )
        current_status = snapshot.get("status", "critical")
        for status in ("healthy", "degraded", "critical"):
            status_metric.add_metric([status], int(status == current_status))
        yield status_metric

        scalar_metrics = (
            (
                "leotrade_live_orders_unknown",
                "Live orders currently in unknown broker state.",
                "live_orders_unknown",
            ),
            (
                "leotrade_live_orders_unknown_beyond_slo",
                "Live orders in unknown broker state beyond the SLO.",
                "live_orders_unknown_beyond_slo",
            ),
            (
                "leotrade_live_orders_stale_submitting",
                "Live orders stuck in the submitting state.",
                "live_orders_stale_submitting",
            ),
            (
                "leotrade_live_portfolios_reconciliation_stale",
                "Live portfolios whose reconciliation is stale.",
                "live_portfolios_reconciliation_stale",
            ),
            (
                "leotrade_live_brokers_unhealthy",
                "Live broker accounts with stale or failed health checks.",
                "live_brokers_unhealthy",
            ),
            (
                "leotrade_outbox_oldest_pending_age_seconds",
                "Age of the oldest pending or processing Outbox event.",
                "outbox_oldest_pending_age_seconds",
            ),
            (
                "leotrade_active_kill_switches",
                "Active portfolio kill switches.",
                "active_kill_switches",
            ),
        )
        for name, description, value_key in scalar_metrics:
            metric = GaugeMetricFamily(name, description)
            metric.add_metric([], int(values.get(value_key) or 0))
            yield metric

        outbox = GaugeMetricFamily(
            "leotrade_outbox_events",
            "Outbox events by operational status.",
            labels=["status"],
        )
        for status in ("pending", "processing", "dead"):
            outbox.add_metric([status], int(values.get(f"outbox_{status}") or 0))
        yield outbox


def register_operational_metrics() -> None:
    global _registered
    if _registered:
        return
    try:
        REGISTRY.register(OperationalMetricsCollector())
    except ValueError:
        logger.warning("monitoring.prometheus_collector_already_registered")
    _registered = True
