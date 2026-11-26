"""
trading/consumers.py
====================

DashboardConsumer : pousse les events agrégés du dashboard hedge fund
("dashboard.update") vers le groupe `user_dashboard_{user_id}`.

Résilient :
  - accept() AVANT group_add → si Redis down, la connexion reste vivante
  - send() best-effort, ne ferme PAS la connexion sur erreur transitoire
  - broadcast_message protégé pour ne pas tuer le client sur un message corrompu
"""

from __future__ import annotations

import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer


logger = logging.getLogger(__name__)


def _json_default(value):
    try:
        return str(value)
    except Exception:
        return None


class DashboardConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close(code=4001)
            return

        self.user_id = user.id
        self.group_name = f"user_dashboard_{self.user_id}"

        # FIX résilience : accept d'abord, group_add ensuite (best-effort).
        # Si Redis tombe, la WS reste ouverte mais sans broadcast — l'utilisateur
        # voit le badge topbar passer en orange/rouge mais pas une boucle de reconnect.
        # Écho du sous-protocole retenu par core.ws_auth : sans lui, un
        # navigateur ferme une connexion authentifiée par JWT.
        await self.accept(subprotocol=self.scope.get("ws_subprotocol"))

        try:
            await self.channel_layer.group_add(self.group_name, self.channel_name)
        except Exception:
            logger.exception(
                "DashboardConsumer.group_add failed user_id=%s — kept alive in isolated mode",
                self.user_id,
            )

        try:
            await self.send(text_data=json.dumps({
                "event": "connection.established",
                "payload": {
                    "user_id": self.user_id,
                    "stream": "dashboard",
                    "version": 1,
                },
            }, default=_json_default))
        except Exception:
            logger.exception("DashboardConsumer.initial_send failed user_id=%s", self.user_id)

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            try:
                await self.channel_layer.group_discard(self.group_name, self.channel_name)
            except Exception:
                logger.warning(
                    "DashboardConsumer.group_discard failed user_id=%s",
                    getattr(self, "user_id", None),
                )

    async def receive(self, text_data=None, bytes_data=None):
        # Échange minimal : ping/pong pour keepalive client
        if not text_data:
            return
        try:
            msg = json.loads(text_data)
        except Exception:
            return
        if msg.get("action") == "ping":
            try:
                await self.send(text_data=json.dumps({
                    "event": "pong",
                    "payload": {"ts": msg.get("ts")},
                }))
            except Exception:
                pass

    async def broadcast_message(self, event):
        """
        Handler pour `channel_layer.group_send(..., {"type": "broadcast.message", ...})`.
        Channels mappe les `.` vers `_`, donc ce handler reçoit les types
        `broadcast.message` ou `broadcast_message` indistinctement.
        """
        try:
            await self.send(text_data=json.dumps({
                "event": event.get("event_type", "dashboard.update"),
                "payload": event.get("payload", {}) or {},
            }, default=_json_default))
        except Exception:
            # On NE FERME PAS la connexion sur un broadcast échoué — on log et on continue.
            logger.exception(
                "DashboardConsumer.broadcast_message failed user_id=%s",
                getattr(self, "user_id", None),
            )
