from __future__ import annotations

from brokers.services.deriv import DerivClient


class DerivMarketService:
    def __init__(self, broker_account):
        self.broker_account = broker_account

    def _client(self) -> DerivClient:
        return DerivClient(
            token=self.broker_account.deriv_token,
            app_id=self.broker_account.deriv_app_id,
        )

    def list_active_symbols(self, product_type: str = "basic") -> dict:
        client = self._client()
        try:
            client.connect()
            client.authorize()
            return client.active_symbols(product_type=product_type)
        finally:
            client.close()

    def get_contracts_for(self, symbol: str) -> dict:
        client = self._client()
        try:
            client.connect()
            client.authorize()
            return client.contracts_for(
                symbol=symbol,
                currency=self.broker_account.deriv_currency or "USD",
            )
        finally:
            client.close()

    def get_account_snapshot(self) -> dict:
        client = self._client()
        try:
            client.connect()
            client.authorize()
            return {
                "balance": client.balance(),
                "portfolio": client.portfolio(),
                "profit_table": client.profit_table(limit=20),
            }
        finally:
            client.close()