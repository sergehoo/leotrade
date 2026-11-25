"""
Consumer temps réel du centre de notifications.

Rejoint le groupe `user_notifications_{id}` (le même que celui utilisé par
RealtimeBroadcastService.broadcast_notification → compatibilité totale avec
le frontend existant : toasts base.html, manager LeoWS).

Ajoute par-dessus le flux existant :
  - envoi du badge non-lu à la connexion,
  - actions entrantes : mark_read, mark_all_read, get_unread_count.

Compatible application mobile Flutter : messages JSON simples
{"action": "..."} entrants, {"type": "...", ...} sortants.
"""

from __future__ import annotations

import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

log = logging.getLogger("lyneci.notifications.ws")


class NotificationCenterConsumer(AsyncJsonWebsocketConsumer):
    @property
    def group_name(self) -> str:
        return f"user_notifications_{self.scope['user'].id}"

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4401)
            return

        # accept() AVANT group_add : si Redis est down, le WS reste vivant
        # (même pattern résilient que BaseUserStreamConsumer).
        await self.accept()
        try:
            await self.channel_layer.group_add(self.group_name, self.channel_name)
        except Exception:
            log.warning("notifications.ws.group_add_failed user_id=%s", user.id)

        await self.send_json({
            "type": "unread.count",
            "count": await self._unread_count(),
        })

    async def disconnect(self, code):
        try:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        except Exception:
            pass

    # ── Messages entrants (frontend / Flutter) ────────────────────────────
    async def receive(self, text_data=None, bytes_data=None):
        try:
            data = json.loads(text_data or "{}")
        except json.JSONDecodeError:
            return
        action = data.get("action")

        if action == "mark_read":
            notification_id = data.get("id")
            if notification_id:
                await self._mark_read(int(notification_id))
                await self.send_json({
                    "type": "unread.count",
                    "count": await self._unread_count(),
                })
        elif action == "mark_all_read":
            await self._mark_all_read()
            await self.send_json({"type": "unread.count", "count": 0})
        elif action == "get_unread_count":
            await self.send_json({
                "type": "unread.count",
                "count": await self._unread_count(),
            })
        elif action == "ping":
            await self.send_json({"type": "pong"})

    # ── Événements du groupe (broadcast_notification) ─────────────────────
    async def notification_created(self, event):
        """Handler de l'événement channel-layer `notification.created`."""
        await self.send_json({
            "type": "notification.created",
            "payload": event.get("payload") or {},
        })
        await self.send_json({
            "type": "unread.count",
            "count": await self._unread_count(),
        })

    # ── DB helpers ─────────────────────────────────────────────────────────
    @database_sync_to_async
    def _unread_count(self) -> int:
        from notifications.services import NotificationService
        return NotificationService.unread_count(self.scope["user"])

    @database_sync_to_async
    def _mark_read(self, notification_id: int):
        from notifications.models import Notification
        notification = Notification.objects.filter(
            pk=notification_id, user=self.scope["user"],
        ).first()
        if notification:
            notification.mark_read()

    @database_sync_to_async
    def _mark_all_read(self):
        from notifications.services import NotificationService
        NotificationService.mark_all_read(self.scope["user"])
