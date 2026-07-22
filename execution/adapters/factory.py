import logging

from .paper import PaperBrokerAdapter
from .live_binance import LiveBinanceAdapter
from .live_mt5 import LiveMT5Adapter
from .live_deriv import LiveDerivAdapter


log = logging.getLogger("lyneci.execution.adapters.factory")


class BrokerAdapterFactory:
    @staticmethod
    def build(broker_account, portfolio):
        """
        Choisit l'adapter approprié pour ce BrokerAccount.

        Règle de routage
        ----------------
        - ``mode == "PAPER"`` → ``PaperBrokerAdapter`` (aucun appel broker,
          le fill est simulé en local). C'est ce qui produit des
          ``broker_order_id`` du type ``PAPER-<id>`` et explique pourquoi
          rien n'apparaît côté Deriv : le PaperBrokerAdapter est conçu
          pour le backtesting et les tests offline.

        - ``mode == "LIVE"`` → adapter live correspondant
          (LiveDerivAdapter / LiveBinanceAdapter / LiveMT5Adapter).
          C'est le seul mode qui appelle réellement le broker.

        Si l'utilisateur a configuré un token Deriv mais laissé le compte
        en PAPER, on loggue un warning structuré explicite : c'est presque
        toujours une erreur de configuration ("je veux trader sur Deriv
        demo mais mode=PAPER simule localement et n'envoie rien").
        """
        if broker_account.mode == "PAPER":
            if (
                broker_account.broker == "DERIV"
                and getattr(broker_account, "deriv_token", None)
            ):
                log.warning(
                    "broker_adapter.paper_used_with_deriv_token "
                    "broker_account_id=%s broker=%s mode=%s deriv_account_type=%s "
                    "— l'ordre sera simulé localement et n'atteindra PAS Deriv. "
                    "Pour exécuter sur Deriv (demo ou réel) passez le compte en mode LIVE.",
                    broker_account.id,
                    broker_account.broker,
                    broker_account.mode,
                    getattr(broker_account, "deriv_account_type", None),
                )
            return PaperBrokerAdapter(broker_account=broker_account, portfolio=portfolio)

        if broker_account.broker == "BINANCE":
            return LiveBinanceAdapter(broker_account=broker_account, portfolio=portfolio)

        if broker_account.broker == "MT5":
            return LiveMT5Adapter(broker_account=broker_account, portfolio=portfolio)

        if broker_account.broker == "DERIV":
            return LiveDerivAdapter(broker_account=broker_account, portfolio=portfolio)

        raise ValueError(f"Broker non supporté : {broker_account.broker}")
