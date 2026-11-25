from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Q
from django.utils import timezone


logger = logging.getLogger("lyneci.monitoring")

MONITORING_SNAPSHOT_CACHE_KEY = "monitoring:operational:snapshot:v1"
MONITORING_ALERT_STATE_CACHE_KEY = "monitoring:operational:alert-state:v1"
MONITORING_COLLECTOR_LOCK_KEY = "monitoring:operational:collector-lock:v1"


class OperationalAlertDeliveryError(RuntimeError):
    pass


def _age_seconds(now: datetime, value: datetime | None) -> int:
    if value is None:
        return 0
    return max(0, int((now - value).total_seconds()))


def collect_operational_snapshot(*, now: datetime | None = None) -> dict:
    from brokers.models import BrokerAccount
    from core.models import OutboxEvent
    from execution.models import Order
    from portfolio.models import Portfolio
    from risk.models import KillSwitchEvent

    now = now or timezone.now()
    submit_cutoff = now - timedelta(
        seconds=int(getattr(settings, "EXECUTION_SUBMIT_STALE_SECONDS", 180))
    )
    unknown_cutoff = now - timedelta(
        seconds=int(getattr(settings, "EXECUTION_UNKNOWN_ALERT_SECONDS", 300))
    )
    reconciliation_cutoff = now - timedelta(
        seconds=int(getattr(settings, "MONITORING_RECONCILIATION_MAX_AGE_SECONDS", 180))
    )
    broker_cutoff = now - timedelta(
        seconds=int(getattr(settings, "MONITORING_BROKER_HEALTH_MAX_AGE_SECONDS", 600))
    )

    order_counts = Order.objects.filter(mode="LIVE").aggregate(
        unknown=Count(
            "id",
            filter=Q(status="UNKNOWN_BROKER_STATE"),
        ),
        unknown_beyond_slo=Count(
            "id",
            filter=Q(
                status="UNKNOWN_BROKER_STATE",
                updated_at__lt=unknown_cutoff,
            ),
        ),
        stale_submitting=Count(
            "id",
            filter=Q(status="SUBMITTING", updated_at__lt=submit_cutoff),
        ),
    )

    stale_live_portfolios = Portfolio.objects.filter(
        is_active=True,
        broker_account__mode="LIVE",
        created_at__lt=reconciliation_cutoff,
    ).filter(
        Q(last_reconciled_at__isnull=True)
        | Q(last_reconciled_at__lt=reconciliation_cutoff)
    ).count()

    unhealthy_live_brokers = BrokerAccount.objects.filter(
        is_active=True,
        mode="LIVE",
        created_at__lt=broker_cutoff,
    ).filter(
        Q(last_connection_status=False)
        | Q(last_connected_at__isnull=True)
        | Q(last_connected_at__lt=broker_cutoff)
        | Q(status="ERROR")
    ).count()

    outbox_counts = OutboxEvent.objects.aggregate(
        pending=Count("id", filter=Q(status="PENDING")),
        processing=Count("id", filter=Q(status="PROCESSING")),
        dead=Count("id", filter=Q(status="DEAD")),
    )
    oldest_outbox = (
        OutboxEvent.objects.filter(status__in=("PENDING", "PROCESSING"))
        .order_by("created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    oldest_outbox_age = _age_seconds(now, oldest_outbox)
    outbox_lag_threshold = int(
        getattr(settings, "MONITORING_OUTBOX_MAX_AGE_SECONDS", 60)
    )
    active_kill_switches = KillSwitchEvent.objects.filter(is_active=True).count()

    values = {
        "live_orders_unknown": int(order_counts["unknown"] or 0),
        "live_orders_unknown_beyond_slo": int(
            order_counts["unknown_beyond_slo"] or 0
        ),
        "live_orders_stale_submitting": int(order_counts["stale_submitting"] or 0),
        "live_portfolios_reconciliation_stale": stale_live_portfolios,
        "live_brokers_unhealthy": unhealthy_live_brokers,
        "outbox_pending": int(outbox_counts["pending"] or 0),
        "outbox_processing": int(outbox_counts["processing"] or 0),
        "outbox_dead": int(outbox_counts["dead"] or 0),
        "outbox_oldest_pending_age_seconds": oldest_outbox_age,
        "outbox_lag_beyond_slo": int(oldest_outbox_age > outbox_lag_threshold),
        "active_kill_switches": active_kill_switches,
    }

    critical = any(
        values[key] > 0
        for key in (
            "live_orders_unknown_beyond_slo",
            "live_orders_stale_submitting",
            "outbox_dead",
        )
    )
    degraded = any(
        values[key] > 0
        for key in (
            "live_orders_unknown",
            "live_portfolios_reconciliation_stale",
            "live_brokers_unhealthy",
            "outbox_lag_beyond_slo",
            "active_kill_switches",
        )
    )

    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "generated_at_epoch": int(now.timestamp()),
        "status": "critical" if critical else "degraded" if degraded else "healthy",
        "values": values,
        "thresholds": {
            "submit_stale_seconds": int(
                getattr(settings, "EXECUTION_SUBMIT_STALE_SECONDS", 180)
            ),
            "unknown_order_seconds": int(
                getattr(settings, "EXECUTION_UNKNOWN_ALERT_SECONDS", 300)
            ),
            "reconciliation_max_age_seconds": int(
                getattr(settings, "MONITORING_RECONCILIATION_MAX_AGE_SECONDS", 180)
            ),
            "broker_health_max_age_seconds": int(
                getattr(settings, "MONITORING_BROKER_HEALTH_MAX_AGE_SECONDS", 600)
            ),
            "outbox_max_age_seconds": outbox_lag_threshold,
        },
    }


def store_operational_snapshot(snapshot: dict) -> None:
    ttl = int(getattr(settings, "MONITORING_SNAPSHOT_TTL_SECONDS", 300))
    cache.set(MONITORING_SNAPSHOT_CACHE_KEY, snapshot, timeout=ttl)


def read_operational_snapshot() -> dict | None:
    try:
        snapshot = cache.get(MONITORING_SNAPSHOT_CACHE_KEY)
    except Exception:
        logger.exception("monitoring.snapshot_read_failed")
        return None
    return snapshot if isinstance(snapshot, dict) else None


def operational_snapshot_age(snapshot: dict | None, *, now=None) -> int | None:
    if not snapshot:
        return None
    generated_at_epoch = snapshot.get("generated_at_epoch")
    if generated_at_epoch is None:
        return None
    now = now or timezone.now()
    return max(0, int(now.timestamp()) - int(generated_at_epoch))


_ISSUES = (
    (
        "live-order-unknown-slo",
        "live_orders_unknown_beyond_slo",
        "CRITICAL",
        "Ordre Live non résolu",
        "Un ordre Live reste dans un état broker inconnu au-delà du SLO.",
    ),
    (
        "live-order-stale-submitting",
        "live_orders_stale_submitting",
        "CRITICAL",
        "Soumission Live bloquée",
        "Un ordre Live reste bloqué pendant sa soumission.",
    ),
    (
        "outbox-dead-letter",
        "outbox_dead",
        "CRITICAL",
        "Événement Outbox en dead-letter",
        "Une commande durable a épuisé toutes ses tentatives de livraison.",
    ),
    (
        "reconciliation-stale",
        "live_portfolios_reconciliation_stale",
        "ERROR",
        "Réconciliation Live en retard",
        "Un portefeuille Live dépasse le délai maximal de réconciliation.",
    ),
    (
        "broker-unhealthy",
        "live_brokers_unhealthy",
        "ERROR",
        "Broker Live indisponible",
        "Un compte broker Live est en erreur ou son contrôle de santé est périmé.",
    ),
    (
        "outbox-lag",
        "outbox_lag_beyond_slo",
        "ERROR",
        "Outbox en retard",
        "La plus ancienne commande durable dépasse le délai de publication.",
    ),
    (
        "kill-switch-active",
        "active_kill_switches",
        "WARNING",
        "Kill switch actif",
        "Au moins un portefeuille bloque actuellement les nouvelles entrées.",
    ),
)


def dispatch_operational_alerts(snapshot: dict) -> dict:
    from core.alerting import send_alert

    values = snapshot.get("values") or {}
    now_epoch = int(snapshot.get("generated_at_epoch") or timezone.now().timestamp())
    repeat_seconds = int(getattr(settings, "MONITORING_ALERT_REPEAT_SECONDS", 900))
    state_ttl = int(getattr(settings, "MONITORING_ALERT_STATE_TTL_SECONDS", 604800))

    try:
        state = cache.get(MONITORING_ALERT_STATE_CACHE_KEY) or {}
    except Exception:
        logger.exception("monitoring.alert_state_read_failed")
        state = {}
    if not isinstance(state, dict):
        state = {}

    sent = recovered = suppressed = 0
    next_state = dict(state)

    def deliver(**kwargs) -> None:
        results = send_alert(**kwargs)
        if isinstance(results, dict) and results and not any(results.values()):
            raise OperationalAlertDeliveryError(
                f"All configured alert channels failed for {kwargs['title']}"
            )

    for code, value_key, level, title, message in _ISSUES:
        value = int(values.get(value_key) or 0)
        previous = state.get(code) if isinstance(state.get(code), dict) else {}
        was_active = bool(previous.get("active"))

        if value > 0:
            last_sent = int(previous.get("last_sent_epoch") or 0)
            should_send = not was_active or now_epoch - last_sent >= repeat_seconds
            if should_send:
                deliver(
                    title=title,
                    message=message,
                    level=level,
                    payload={
                        "issue_code": code,
                        "current_value": value,
                        "operational_snapshot": snapshot,
                    },
                )
                sent += 1
                last_sent = now_epoch
            else:
                suppressed += 1
            next_state[code] = {
                "active": True,
                "first_seen_epoch": int(
                    previous.get("first_seen_epoch") or now_epoch
                ),
                "last_seen_epoch": now_epoch,
                "last_sent_epoch": last_sent,
            }
        elif was_active:
            deliver(
                title=f"Rétablissement : {title}",
                message="La condition opérationnelle est revenue à la normale.",
                level="INFO",
                payload={
                    "issue_code": code,
                    "resolved_at_epoch": now_epoch,
                    "operational_snapshot": snapshot,
                },
            )
            recovered += 1
            next_state.pop(code, None)

    try:
        if next_state:
            cache.set(
                MONITORING_ALERT_STATE_CACHE_KEY,
                next_state,
                timeout=state_ttl,
            )
        else:
            cache.delete(MONITORING_ALERT_STATE_CACHE_KEY)
    except Exception:
        logger.exception("monitoring.alert_state_write_failed")

    return {
        "sent": sent,
        "recovered": recovered,
        "suppressed": suppressed,
        "active": len(next_state),
    }
