from __future__ import annotations

from infrastructure.broker_clients import BrokerClientFactory
from .base import BaseBrokerAdapter


class LiveBinanceAdapter(BaseBrokerAdapter):
    def __init__(self, broker_account, portfolio):
        super().__init__(broker_account, portfolio)
        self.client = BrokerClientFactory.build(broker_account)

    def submit_order(self, order):
        return self.client.submit_order(order)

    def cancel_order(self, order):
        return self.client.cancel_order(order)

    def fetch_open_orders(self):
        return self.client.fetch_open_orders()

    def fetch_positions(self):
        return self.client.fetch_positions()

    def fetch_balance(self):
        return self.client.fetch_balances()

# from __future__ import annotations
#
# from .base import BaseBrokerAdapter
#
#
# class LiveBinanceAdapter(BaseBrokerAdapter):
#     def submit_order(self, order):
#         api_key = self.broker_account.api_key
#         api_secret = self.broker_account.api_secret
#         if not api_key or not api_secret:
#             raise ValueError("Credentials Binance manquants.")
#
#         # TODO: brancher le vrai client Binance
#         raise NotImplementedError("Adapter Binance live à brancher.")
#
#     def cancel_order(self, order):
#         raise NotImplementedError("Cancel Binance live à brancher.")
#
#     def fetch_open_orders(self):
#         return []
#
#     def fetch_positions(self):
#         return []
#
#     def fetch_balance(self):
#         return None