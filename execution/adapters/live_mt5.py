from __future__ import annotations

from infrastructure.broker_clients import BrokerClientFactory
from .base import BaseBrokerAdapter


class LiveMT5Adapter(BaseBrokerAdapter):
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
# class LiveMT5Adapter(BaseBrokerAdapter):
#     def submit_order(self, order):
#         password = self.broker_account.password
#         if not self.broker_account.login or not password or not self.broker_account.server:
#             raise ValueError("Credentials MT5 incomplètes.")
#
#         # TODO: brancher MetaTrader5
#         raise NotImplementedError("Adapter MT5 live à brancher.")
#
#     def cancel_order(self, order):
#         raise NotImplementedError("Cancel MT5 live à brancher.")
#
#     def fetch_open_orders(self):
#         return []
#
#     def fetch_positions(self):
#         return []
#
#     def fetch_balance(self):
#         return None