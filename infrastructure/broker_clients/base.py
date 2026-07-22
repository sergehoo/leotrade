from __future__ import annotations

from abc import ABC, abstractmethod


class BaseBrokerClient(ABC):
    def __init__(self, broker_account):
        self.broker_account = broker_account

    @abstractmethod
    def test_connection(self):
        raise NotImplementedError

    @abstractmethod
    def fetch_balances(self):
        raise NotImplementedError

    @abstractmethod
    def fetch_positions(self):
        raise NotImplementedError

    @abstractmethod
    def fetch_open_orders(self):
        raise NotImplementedError

    @abstractmethod
    def fetch_order(self, order):
        """Retourne l'état broker d'un ordre précis, ou ``None`` s'il est absent."""
        raise NotImplementedError

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
    def fetch_symbol_constraints(self, symbol: str):
        raise NotImplementedError
