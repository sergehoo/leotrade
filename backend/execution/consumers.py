from __future__ import annotations

import json
import logging
from typing import Any

from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)


class BaseUserStreamConsumer(AsyncWebsocketConsumer):
    """
    Consumer WebSocket de base pour les flux temps réel par utilisateur.
    Les sous-classes doivent définir :
      - stream_name
      - group_prefix
    """

    stream_name: str = ""
    group_prefix: str = ""

    async def connect(self):
        user = self.scope.get("user")

        if not user or not user.is_authenticated:
            logger.warning(
                "WebSocket refused: anonymous user on stream=%s",
                self.stream_name,
            )
            await self.close(code=4001)
            return

        self.user = user
        self.user_id = user.id
        self.group_name = f"{self.group_prefix}_{self.user_id}"

        # FIX (résilience) : on ACCEPT d'abord, puis on s'inscrit au groupe.
        # Avant : un seul try/except enveloppait `group_add` ET `accept` ET `send_json`.
        # Si `send_json` plantait (sérialisation, write race, etc.), le bloc except
        # fermait la connexion avec code 4500 → côté client : "open" puis "close"
        # immédiat → boucle de reconnexion LeoWS toutes les 1-60s.
        # Désormais : accept ne peut pas être annulé par un bug de groupe ou de
        # send. Si group_add échoue (Redis down), on log un warning mais on
        # garde la connexion vivante en mode "isolated" (les broadcasts ne
        # parviendront pas à ce client tant que le groupe n'est pas joint).
        await self.accept()

        # Inscription au groupe Redis — best-effort, ne ferme pas la WS
        try:
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            logger.info(
                "WebSocket connected: stream=%s user_id=%s channel=%s",
                self.stream_name,
                self.user_id,
                self.channel_name,
            )
        except Exception:
            logger.exception(
                "WebSocket group_add failed (Redis down?): stream=%s user_id=%s — connection kept alive in isolated mode",
                self.stream_name,
                self.user_id,
            )

        # Message d'établissement — best-effort
        try:
            await self.send_json(
                event="connection.established",
                payload={
                    "user_id": self.user_id,
                    "stream": self.stream_name,
                },
            )
        except Exception:
            logger.exception(
                "WebSocket initial send_json failed: stream=%s user_id=%s — ignored",
                self.stream_name,
                self.user_id,
            )

    async def disconnect(self, close_code):
        try:
            if getattr(self, "group_name", None):
                await self.channel_layer.group_discard(self.group_name, self.channel_name)

            logger.info(
                "WebSocket disconnected: stream=%s user_id=%s close_code=%s",
                self.stream_name,
                getattr(self, "user_id", None),
                close_code,
            )
        except Exception:
            logger.exception(
                "WebSocket disconnect cleanup failed: stream=%s user_id=%s",
                self.stream_name,
                getattr(self, "user_id", None),
            )

    async def receive(self, text_data=None, bytes_data=None):
        """
        Protocole entrant minimal :
        - ping => pong
        - subscribe/unsubscribe ignorés pour l’instant
        """
        if bytes_data is not None:
            await self.send_json(
                event="error",
                payload={"message": "Binary frames are not supported."},
            )
            return

        if not text_data:
            return

        try:
            message = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send_json(
                event="error",
                payload={"message": "Invalid JSON payload."},
            )
            return

        action = message.get("action")

        if action == "ping":
            await self.send_json(
                event="pong",
                payload={"ts": message.get("ts")},
            )
            return

        await self.send_json(
            event="ack",
            payload={
                "message": "Message reçu.",
                "action": action,
            },
        )

    async def broadcast_message(self, event: dict[str, Any]):
        """
        Handler appelé par channel_layer.group_send(..., {"type": "broadcast_message", ...}).

        FIX résilience : on NE FERME PLUS la connexion sur erreur. Un message
        corrompu (rare, ex: payload trop gros, encoding bizarre) ne doit pas
        tuer toute la session WS du client. On log et on continue.
        """
        try:
            event_type = event.get("event_type", "message")
            payload = event.get("payload", {}) or {}

            await self.send_json(
                event=event_type,
                payload=payload,
            )
        except Exception:
            logger.exception(
                "WebSocket broadcast send failed (kept alive): stream=%s user_id=%s",
                self.stream_name,
                getattr(self, "user_id", None),
            )

    async def send_json(self, event: str, payload: dict[str, Any] | None = None):
        await self.send(
            text_data=json.dumps(
                {
                    "event": event,
                    "payload": payload or {},
                },
                default=self._json_default,
            )
        )

    @staticmethod
    def _json_default(value):
        """
        Sérialisation défensive pour Decimal, datetime, UUID, etc.
        """
        try:
            return str(value)
        except Exception:
            return None


class UserOrdersConsumer(BaseUserStreamConsumer):
    stream_name = "orders"
    group_prefix = "user_orders"


class UserNotificationsConsumer(BaseUserStreamConsumer):
    stream_name = "notifications"
    group_prefix = "user_notifications"