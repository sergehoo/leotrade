from __future__ import annotations

from abc import ABC, abstractmethod


class BaseBrokerAdapter(ABC):
    def __init__(self, broker_account, portfolio):
        self.broker_account = broker_account
        self.portfolio = portfolio

    @abstractmethod
    def submit_order(self, order):
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, order):
        raise NotImplementedError

    @abstractmethod
    def close_position(self, position, order):
        raise NotImplementedError

    @abstractmethod
    def fetch_open_orders(self):
        raise NotImplementedError

    @abstractmethod
    def fetch_order(self, order):
        raise NotImplementedError

    @abstractmethod
    def fetch_positions(self):
        raise NotImplementedError

    @abstractmethod
    def fetch_balance(self):
        raise NotImplementedError
