import json
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from portfolio.models import Portfolio


class PortfolioConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close(code=4001)
            return

        self.portfolio_id = int(self.scope["url_route"]["kwargs"]["portfolio_id"])

        has_access = await self._user_has_access(user.id, self.portfolio_id)
        if not has_access:
            await self.close(code=4003)
            return

        self.group_name = f"portfolio_{self.portfolio_id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        await self.send(text_data=json.dumps({
            "event": "connection.established",
            "payload": {
                "portfolio_id": self.portfolio_id,
                "group": self.group_name,
            }
        }))

    @database_sync_to_async
    def _user_has_access(self, user_id: int, portfolio_id: int) -> bool:
        return Portfolio.objects.filter(id=portfolio_id, user_id=user_id).exists()

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