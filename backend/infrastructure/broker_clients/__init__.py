from infrastructure.broker_clients.binance_client import BinanceBrokerClient
from infrastructure.broker_clients.mt5_client import MT5BrokerClient
from infrastructure.broker_clients.deriv_client import DerivBrokerClient


class BrokerClientFactory:
    @staticmethod
    def build(broker_account):
        if broker_account.broker == "BINANCE":
            return BinanceBrokerClient(broker_account)
        if broker_account.broker == "MT5":
            return MT5BrokerClient(broker_account)
        if broker_account.broker == "DERIV":
            return DerivBrokerClient(broker_account)
        if broker_account.broker == "SIMULATION":
            raise ValueError(
                "Compte de simulation : aucune place distante à joindre. "
                "L'exécution passe par PaperBrokerAdapter, en local."
            )
        raise ValueError(f"Broker non supporté: {broker_account.broker}")