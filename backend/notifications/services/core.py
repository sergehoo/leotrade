"""
NotificationService — point d'entrée unique du module.

    from notifications.services import NotificationService
    NotificationService.notify(
        user, "ORDER_FILLED",
        title="Ordre exécuté : BUY R_75",
        message="10 lots exécutés à 1 234,56 $.",
        payload={"order_id": 42, "symbol": "R_75"},
    )

Garanties :
  - Ne lève JAMAIS vers l'appelant (un trade ne doit pas échouer à cause
    d'une notification) — tout est try/except + log.
  - L'envoi effectif passe par l'Outbox transactionnel puis Celery.
  - Anti-spam : rate limit par (user, event_type) via le cache Redis,
    les événements critiques en sont exemptés.
  - Chaque tentative par canal est journalisée (NotificationDeliveryLog).
"""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from core.outbox import OutboxService
from notifications.event_topics import NOTIFICATION_DISPATCH_REQUESTED
from notifications.events import Channel, get_event
from notifications.services.email import EmailNotificationService
from notifications.services.in_app import InAppNotificationService
from notifications.services.preferences import NotificationPreferenceService
from notifications.services.sms import SMSNotificationService
from notifications.services.whatsapp import WhatsAppNotificationService

log = logging.getLogger("leotrade.notifications")

CHANNEL_SERVICES = {
    Channel.EMAIL: EmailNotificationService,
    Channel.IN_APP: InAppNotificationService,
    Channel.SMS: SMSNotificationService,
    Channel.WHATSAPP: WhatsAppNotificationService,
}

# Anti-spam : max N notifications par (user, event_type) par fenêtre.
RATE_LIMIT_MAX = 10
RATE_LIMIT_WINDOW_SECONDS = 3600


class NotificationService:
    # ------------------------------------------------------------------
    # Création + dispatch
    # ------------------------------------------------------------------
    @classmethod
    def notify(
        cls,
        user,
        event_type: str,
        *,
        title: str | None = None,
        message: str | None = None,
        payload: dict | None = None,
        severity: str | None = None,
        priority: str | None = None,
        channels: list[str] | None = None,
        dedupe_key: str | None = None,
    ):
        """Crée la notification et planifie l'envoi. Retourne la Notification
        (ou None si supprimée/erreur). Ne lève jamais."""
        try:
            return cls._notify(
                user, event_type,
                title=title, message=message, payload=payload,
                severity=severity, priority=priority,
                channels=channels, dedupe_key=dedupe_key,
            )
        except Exception:
            log.exception("notify.failed event=%s user_id=%s",
                          event_type, getattr(user, "id", None))
            return None

    @classmethod
    def _notify(cls, user, event_type, *, title, message, payload,
                severity, priority, channels, dedupe_key):
        from notifications.models import Notification

        if user is None or not getattr(user, "pk", None):
            return None

        spec = get_event(event_type)
        severity = severity or spec.severity
        priority = priority or spec.priority

        # Déduplication optionnelle (ex. une seule notif par kill switch event)
        if dedupe_key:
            dedupe_cache_key = f"notif:dedupe:{user.pk}:{dedupe_key}"
            if not cache.add(dedupe_cache_key, 1, timeout=RATE_LIMIT_WINDOW_SECONDS):
                return None

        # Anti-spam (les critiques passent toujours)
        if not spec.critical and cls._rate_limited(user.pk, event_type):
            log.info("notify.rate_limited event=%s user_id=%s", event_type, user.pk)
            return None

        resolved, suppress_reason = NotificationPreferenceService.resolve_channels(
            user, event_type, priority, requested=channels,
        )

        with transaction.atomic():
            notification = Notification.objects.create(
                user=user,
                title=(title or spec.label)[:200],
                message=message or spec.label,
                event_type=event_type,
                severity=severity,
                priority=priority,
                channels_requested=resolved,
                payload=payload or {},
                status="SUPPRESSED" if (suppress_reason or not resolved) else "PENDING",
            )

            if notification.status == "PENDING":
                OutboxService.enqueue(
                    topic=NOTIFICATION_DISPATCH_REQUESTED,
                    aggregate_type="notifications.Notification",
                    aggregate_id=notification.id,
                    payload={"notification_id": notification.id},
                    idempotency_key=f"notification:{notification.id}:dispatch",
                )
        return notification

    @staticmethod
    def _rate_limited(user_id: int, event_type: str) -> bool:
        key = f"notif:rl:{user_id}:{event_type}"
        try:
            current = cache.get_or_set(key, 0, timeout=RATE_LIMIT_WINDOW_SECONDS)
            if current >= RATE_LIMIT_MAX:
                return True
            try:
                cache.incr(key)
            except ValueError:
                cache.set(key, 1, timeout=RATE_LIMIT_WINDOW_SECONDS)
            return False
        except Exception:
            return False  # cache indisponible → on n'étouffe pas la notif

    # ------------------------------------------------------------------
    # Envoi effectif (appelé par la tâche Celery)
    # ------------------------------------------------------------------
    @classmethod
    def dispatch(cls, notification) -> dict:
        """Envoie la notification sur chaque canal demandé, journalise tout,
        met à jour status/channels_sent."""
        from notifications.models import NotificationDeliveryLog

        pref = NotificationPreferenceService.get_or_create(notification.user)
        language = pref.preferred_language or "fr"

        sent, failed = [], []
        for channel in notification.channels_requested or []:
            service = CHANNEL_SERVICES.get(channel)
            if service is None:
                continue
            entry = NotificationDeliveryLog.objects.create(
                notification=notification,
                channel=channel,
                provider=service.provider,
                status="PENDING",
                request_payload={
                    "title": notification.title,
                    "event_type": notification.event_type,
                    "language": language,
                },
            )
            try:
                result = service.send(notification, language=language)
            except Exception as exc:  # un canal ne doit pas bloquer les autres
                result = {"ok": False, "skipped": False, "recipient": "",
                          "provider": service.provider, "response": {},
                          "error": str(exc)[:1000]}

            entry.provider = result.get("provider") or service.provider
            entry.recipient = result.get("recipient", "")
            entry.response_payload = result.get("response") or {}
            entry.error_message = result.get("error", "")
            if result.get("ok"):
                entry.status = "SENT"
                entry.sent_at = timezone.now()
                sent.append(channel)
            elif result.get("skipped"):
                entry.status = "SKIPPED"
            else:
                entry.status = "FAILED"
                failed.append(channel)
            entry.save()

        notification.channels_sent = sent
        if sent and not failed:
            notification.status = "SENT"
        elif sent and failed:
            notification.status = "PARTIAL"
        elif failed:
            notification.status = "FAILED"
        else:
            notification.status = "SUPPRESSED"
        notification.save(update_fields=["channels_sent", "status", "updated_at"])

        return {"sent": sent, "failed": failed, "status": notification.status}

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------
    @classmethod
    def unread_count(cls, user) -> int:
        from notifications.models import Notification
        return Notification.objects.filter(user=user, read_at__isnull=True).count()

    @classmethod
    def mark_all_read(cls, user) -> int:
        from notifications.models import Notification
        return Notification.objects.filter(user=user, read_at__isnull=True).update(
            read_at=timezone.now()
        )
