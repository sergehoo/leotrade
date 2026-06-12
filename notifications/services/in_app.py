"""
InAppNotificationService — temps réel via Django Channels.

Réutilise le groupe existant `user_notifications_{id}` et l'événement
`notification.created` (déjà consommés par le frontend : toast LeoAnim +
badge topbar). La persistance PostgreSQL est assurée par le modèle
Notification lui-même — ce service ne fait que le push WebSocket.
"""

from __future__ import annotations

import logging

from core.realtime import RealtimeBroadcastService

log = logging.getLogger("leotrade.notifications.in_app")


class InAppNotificationService:
    provider = "channels"

    @classmethod
    def send(cls, notification, language: str = "fr") -> dict:
        payload = {
            "id": notification.id,
            "kind": notification.severity.lower(),       # success/info/warning/critical
            "title": notification.title,
            "message": notification.message,
            "event_type": notification.event_type,
            "severity": notification.severity,
            "priority": notification.priority,
            "created_at": notification.created_at.isoformat() if notification.created_at else None,
            "payload": notification.payload or {},
        }
        try:
            delivered = RealtimeBroadcastService.broadcast_notification(
                user_id=notification.user_id, payload=payload,
            )
            # delivered=False = channel layer indisponible : la notification
            # reste lisible dans le centre (PostgreSQL), on ne considère pas
            # ça comme un échec dur.
            return {
                "ok": True,
                "recipient": f"user:{notification.user_id}",
                "provider": cls.provider,
                "response": {"ws_delivered": bool(delivered)},
                "error": "",
            }
        except Exception as exc:
            log.warning("in_app.send_failed notification_id=%s err=%s", notification.id, exc)
            return {
                "ok": False, "recipient": f"user:{notification.user_id}",
                "provider": cls.provider, "response": {}, "error": str(exc)[:1000],
            }
