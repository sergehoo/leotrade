import json
from channels.generic.websocket import AsyncWebsocketConsumer


class AIRadarConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close(code=4001)
            return

        self.user_id = user.id
        self.group_name = f"user_ai_{self.user_id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        # Écho du sous-protocole retenu par core.ws_auth : sans lui, un
        # navigateur ferme une connexion authentifiée par JWT.
        await self.accept(subprotocol=self.scope.get("ws_subprotocol"))

        await self.send(text_data=json.dumps({
            "event": "connection.established",
            "payload": {
                "stream": "ai_radar",
                "user_id": self.user_id,
            }
        }))

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        return

    async def broadcast_message(self, event):
        await self.send(text_data=json.dumps({
            "event": event["event_type"],
            "payload": event["payload"],
        }))