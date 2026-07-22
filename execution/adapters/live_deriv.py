from __future__ import annotations

from infrastructure.broker_clients.gateway import BrokerGateway
from .base import BaseBrokerAdapter


class LiveDerivAdapter(BaseBrokerAdapter):
    def __init__(self, broker_account, portfolio):
        super().__init__(broker_account, portfolio)
        self.client = BrokerGateway(broker_account)

    def submit_order(self, order):
        return self.client.submit_order(order)

    def cancel_order(self, order):
        return self.client.cancel_order(order)

    def close_position(self, position, order):
        return self.client.close_position(position, order)

    def fetch_open_orders(self):
        return self.client.fetch_open_orders()

    def fetch_order(self, order):
        return self.client.fetch_order(order)

    def fetch_positions(self):
        return self.client.fetch_positions()

    def fetch_balance(self):
        return self.client.fetch_balances()

# from __future__ import annotations
#
# from .base import BaseBrokerAdapter
#
#
# class LiveDerivAdapter(BaseBrokerAdapter):
#     def submit_order(self, order):
#         token = self.broker_account.deriv_token
#         if not token:
#             raise ValueError("Token Deriv manquant.")
#
#         # TODO: brancher le client Deriv
#         raise NotImplementedError("Adapter Deriv live à brancher.")
#
#     def cancel_order(self, order):
#         raise NotImplementedError("Cancel Deriv live à brancher.")
#
#     def fetch_open_orders(self):
#         return []
#
#     def fetch_positions(self):
#         return []
#
#     def fetch_balance(self):
#         return None
