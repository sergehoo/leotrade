# market/consumers.py
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer


class CandleConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.asset_id = self.scope["url_route"]["kwargs"]["asset_id"]
        self.timeframe = self.scope["url_route"]["kwargs"]["timeframe"]
        self.group_name = f"candles_{self.asset_id}_{self.timeframe}"

        user = self.scope.get("user")
        if not user or user.is_anonymous:
            # 4401 = not authenticated (custom WS close code)
            await self.close(code=4401)
            return

        # Vérifie que l'asset existe et que l'utilisateur a un portefeuille actif.
        # Sans ce contrôle, n'importe quel utilisateur authentifié pouvait
        # s'abonner à n'importe quel flux de bougies — y compris des assets
        # non exposés à l'utilisateur (risque d'information disclosure).
        has_access = await self._check_asset_access(user)
        if not has_access:
            # 4403 = forbidden (custom WS close code)
            await self.close(code=4403)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def candle_update(self, event):
        await self.send_json(event["data"])

    @database_sync_to_async
    def _check_asset_access(self, user) -> bool:
        """
        Deux conditions cumulatives :
        1. L'asset demandé existe et est actif.
        2. L'utilisateur a au moins un portefeuille actif (= abonnement premium).

        On n'effectue PAS de jointure Asset↔Portfolio ici car les assets de
        marché (BTC, ETH…) sont globaux. La condition d'abonnement suffit à
        empêcher les requêtes non autorisées tout en restant simple à maintenir.
        """
        try:
            from market.models import Asset
            from portfolio.models import Portfolio

            asset_ok = Asset.objects.filter(
                pk=self.asset_id,
                is_active=True,
            ).exists()

            if not asset_ok:
                return False

            return Portfolio.objects.filter(
                user=user,
                is_active=True,
            ).exists()
        except Exception:
            return False
