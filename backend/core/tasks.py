from __future__ import annotations

from datetime import timedelta
import logging
import uuid

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from core.models import OutboxEvent
from core.monitoring import (
    MONITORING_COLLECTOR_LOCK_KEY,
    OperationalAlertDeliveryError,
    collect_operational_snapshot,
    dispatch_operational_alerts,
    store_operational_snapshot,
)
from core.outbox import OutboxPublisher


logger = logging.getLogger("leotrade.monitoring")


@shared_task(
    name="core.tasks.publish_outbox_events_task",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def publish_outbox_events_task(self, limit: int | None = None):
    return OutboxPublisher.publish_pending(limit=limit)


@shared_task(name="core.tasks.cleanup_published_outbox_events_task")
def cleanup_published_outbox_events_task(retention_days: int | None = None):
    days = retention_days or int(getattr(settings, "OUTBOX_RETENTION_DAYS", 30))
    deleted, _ = OutboxEvent.objects.filter(
        status="PUBLISHED",
        published_at__lt=timezone.now() - timedelta(days=days),
    ).delete()
    return {"deleted": deleted}


@shared_task(
    name="core.tasks.collect_operational_snapshot_task",
    acks_late=True,
    reject_on_worker_lost=True,
)
def collect_operational_snapshot_task():
    lock_timeout = int(getattr(settings, "MONITORING_COLLECTOR_LOCK_SECONDS", 25))
    lock_token = uuid.uuid4().hex
    if not cache.add(
        MONITORING_COLLECTOR_LOCK_KEY,
        lock_token,
        timeout=lock_timeout,
    ):
        return {"status": "skipped", "reason": "collector_locked"}

    snapshot = collect_operational_snapshot()
    store_operational_snapshot(snapshot)
    try:
        dispatch_operational_alerts_task.delay(snapshot)
    except Exception:
        logger.exception("monitoring.alert_dispatch_enqueue_failed")
    return snapshot


@shared_task(
    name="core.tasks.dispatch_operational_alerts_task",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def dispatch_operational_alerts_task(self, snapshot: dict):
    try:
        return dispatch_operational_alerts(snapshot)
    except OperationalAlertDeliveryError as exc:
        raise self.retry(exc=exc)
