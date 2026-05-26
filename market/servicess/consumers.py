# market/consumers.py
from channels.generic.websocket import AsyncJsonWebsocketConsumer


class CandleConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.asset_id = self.scope["url_route"]["kwargs"]["asset_id"]
        self.timeframe = self.scope["url_route"]["kwargs"]["timeframe"]
        self.group_name = f"candles_{self.asset_id}_{self.timeframe}"

        user = self.scope.get("user")
        if not user or user.is_anonymous:
            await self.close()
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def candle_update(self, event):
        await self.send_json(event["data"])