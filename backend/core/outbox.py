from __future__ import annotations

import logging
from datetime import timedelta
from typing import Callable

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from core.models import OutboxEvent


logger = logging.getLogger("leotrade.outbox")
OutboxHandler = Callable[[OutboxEvent], None]
_HANDLERS: dict[str, OutboxHandler] = {}


class OutboxDeliveryError(RuntimeError):
    pass


def register_outbox_handler(topic: str):
    def decorator(handler: OutboxHandler):
        existing = _HANDLERS.get(topic)
        if existing and existing is not handler:
            same_handler = (
                existing.__module__ == handler.__module__
                and existing.__name__ == handler.__name__
            )
            if not same_handler:
                raise RuntimeError(f"Outbox handler already registered for {topic}")
        _HANDLERS[topic] = handler
        return handler

    return decorator


def _nudge_publisher() -> None:
    try:
        if not cache.add("outbox:publisher:nudge", 1, timeout=1):
            return
        from core.tasks import publish_outbox_events_task

        publish_outbox_events_task.delay()
    except Exception:
        logger.exception("outbox.publisher_nudge_failed")


class OutboxService:
    @staticmethod
    def enqueue(
        *,
        topic: str,
        aggregate_type: str,
        aggregate_id,
        payload: dict | None = None,
        idempotency_key: str | None = None,
        available_at=None,
        nudge: bool = True,
    ) -> OutboxEvent:
        values = {
            "topic": topic,
            "aggregate_type": aggregate_type,
            "aggregate_id": str(aggregate_id),
            "payload": payload or {},
            "available_at": available_at or timezone.now(),
        }

        if idempotency_key:
            try:
                with transaction.atomic():
                    event, created = OutboxEvent.objects.get_or_create(
                        idempotency_key=idempotency_key,
                        defaults=values,
                    )
            except IntegrityError:
                event = OutboxEvent.objects.get(idempotency_key=idempotency_key)
                created = False
        else:
            event = OutboxEvent.objects.create(**values)
            created = True

        if created and nudge:
            transaction.on_commit(_nudge_publisher)
        return event


class OutboxPublisher:
    @classmethod
    def publish_pending(cls, *, limit: int | None = None) -> dict:
        batch_size = limit or int(getattr(settings, "OUTBOX_BATCH_SIZE", 100))
        cls._recover_stale_claims()
        events = cls._claim_batch(batch_size)
        stats = {"claimed": len(events), "published": 0, "retried": 0, "dead": 0}

        for event in events:
            try:
                handler = _HANDLERS.get(event.topic)
                if handler is None:
                    raise OutboxDeliveryError(
                        f"No outbox handler registered for topic {event.topic}"
                    )
                handler(event)
            except Exception as exc:
                outcome = cls._mark_failed(event, exc)
                stats[outcome] += 1
                logger.exception(
                    "outbox.publish_failed event_id=%s topic=%s attempt=%s",
                    event.event_id,
                    event.topic,
                    event.attempts,
                )
            else:
                OutboxEvent.objects.filter(
                    pk=event.pk,
                    status="PROCESSING",
                ).update(
                    status="PUBLISHED",
                    published_at=timezone.now(),
                    locked_at=None,
                    last_error="",
                    updated_at=timezone.now(),
                )
                stats["published"] += 1

        return stats

    @staticmethod
    def _claim_batch(limit: int) -> list[OutboxEvent]:
        now = timezone.now()
        with transaction.atomic():
            queryset = OutboxEvent.objects.filter(
                status="PENDING",
                available_at__lte=now,
            ).order_by("available_at", "id")
            if connection.features.has_select_for_update:
                queryset = queryset.select_for_update(
                    skip_locked=connection.features.has_select_for_update_skip_locked
                )
            events = list(queryset[:limit])
            for event in events:
                event.status = "PROCESSING"
                event.locked_at = now
                event.attempts += 1
                event.save(update_fields=[
                    "status",
                    "locked_at",
                    "attempts",
                    "updated_at",
                ])
        return events

    @staticmethod
    def _recover_stale_claims() -> int:
        lock_timeout = int(getattr(settings, "OUTBOX_LOCK_TIMEOUT_SECONDS", 300))
        stale_before = timezone.now() - timedelta(seconds=lock_timeout)
        return OutboxEvent.objects.filter(
            status="PROCESSING",
            locked_at__lt=stale_before,
        ).update(
            status="PENDING",
            locked_at=None,
            available_at=timezone.now(),
            updated_at=timezone.now(),
        )

    @staticmethod
    def _mark_failed(event: OutboxEvent, exc: Exception) -> str:
        max_attempts = int(getattr(settings, "OUTBOX_MAX_ATTEMPTS", 8))
        error = f"{type(exc).__name__}: {exc}"[:4000]
        now = timezone.now()
        if event.attempts >= max_attempts:
            OutboxEvent.objects.filter(pk=event.pk, status="PROCESSING").update(
                status="DEAD",
                locked_at=None,
                last_error=error,
                updated_at=now,
            )
            return "dead"

        base_delay = int(getattr(settings, "OUTBOX_RETRY_BASE_SECONDS", 2))
        max_delay = int(getattr(settings, "OUTBOX_RETRY_MAX_SECONDS", 300))
        delay = min(max_delay, base_delay * (2 ** max(0, event.attempts - 1)))
        OutboxEvent.objects.filter(pk=event.pk, status="PROCESSING").update(
            status="PENDING",
            locked_at=None,
            available_at=now + timedelta(seconds=delay),
            last_error=error,
            updated_at=now,
        )
        return "retried"
