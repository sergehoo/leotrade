# /Users/ogahserge/Documents/leoTrade/infrastructure/broker_clients/deriv_client.py
"""
infrastructure/broker_clients/deriv_client.py
=============================================

Client Deriv réel utilisé par les sync ponctuelles (fetch_balances, fetch_positions)
et par l'adapter d'exécution (submit_order, cancel_order).

Le streaming temps réel passe par brokers/services/deriv_streamer.py.

Hérite de BaseBrokerClient. Implémentation des méthodes auparavant en stub.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from infrastructure.broker_clients.base import BaseBrokerClient
from infrastructure.broker_clients.dto import (
    BrokerBalanceDTO,
    BrokerPositionDTO,
    BrokerConstraintDTO,
)


log = logging.getLogger("leotrade.deriv.client")
logger = logging.getLogger(__name__)

def _d(value, default: str = "0") -> Decimal:
    try:
        if value is None or value == "":
            return Decimal(default)
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


# Mapping côté LeoTrade ↔ Deriv pour les options binaires
SIDE_TO_CONTRACT_TYPE = {
    "BUY": "CALL",
    "SELL": "PUT",
}

SIDE_TO_MULTIPLIER_CONTRACT_TYPE = {
    "BUY": "MULTUP",
    "SELL": "MULTDOWN",
}


class DerivBrokerClient(BaseBrokerClient):
    """
    Client Deriv : ouvre une session WS courte par appel (one-shot).
    Pour le streaming continu (balance, ticks, contracts), utiliser
    brokers.services.deriv_streamer.DerivStreamer.
    """

    def _validate_deriv_contract_available(
            self,
            *,
            contracts_resp: dict,
            symbol: str,
            contract_type: str,
            duration_unit: str,
    ) -> None:
        available = []

        contracts_for = (contracts_resp or {}).get("contracts_for") or {}
        contracts = contracts_for.get("available") or []

        for item in contracts:
            item_contract_type = str(item.get("contract_type") or "").upper()
            item_duration_unit = str(item.get("duration_unit") or "").lower()

            available.append({
                "contract_type": item_contract_type,
                "duration_unit": item_duration_unit,
            })

            if (
                    item_contract_type == contract_type.upper()
                    and (
                    not item_duration_unit
                    or item_duration_unit == str(duration_unit).lower()
            )
            ):
                return

        raise ValueError(
            f"Contrat Deriv indisponible pour {symbol}: "
            f"contract_type={contract_type}, duration_unit={duration_unit}. "
            f"Contrats disponibles: {available[:10]}"
        )
    def __init__(self, broker_account):
        super().__init__(broker_account)
        token = broker_account.deriv_token
        if not token:
            raise ValueError("Token Deriv manquant.")
        self.token = token
        self.app_id = (
            getattr(broker_account, "deriv_app_id", None)
            or getattr(broker_account, "deriv_client_id", None)
            or "1089"
        )

    # ------------------------------------------------------------------
    # Helpers WS
    # ------------------------------------------------------------------
    def _open_authenticated_ws(self):
        """
        Ouvre une session WS authentifiée via le flux OTP officiel Deriv :
          1. REST  → list_options_accounts()       pour obtenir le Deriv account_id
          2. REST  → get_otp_ws_url(account_id)    pour obtenir l'URL WS éphémère
          3. WS    → connect_with_otp_url(url)     connexion pré-authentifiée
          4. WS    → authorize(token)              confirmation session

        C'est le même flux que les tâches de sync (tasks_deriv_sync.py).
        connect_public() est réservé aux flux de données publics (ticks, actifs) ;
        elle ne supporte PAS les opérations de trading (proposal / buy).
        """
        from brokers.services.deriv import DerivClient

        client = DerivClient(token=self.token, app_id=str(self.app_id))

        # 1. Récupérer la liste des comptes options
        try:
            accounts_resp = client.list_options_accounts()
        except Exception as exc:
            raise RuntimeError(
                f"Deriv list_options_accounts échoué: {exc}"
            ) from exc

        accounts = accounts_resp.get("data") or []
        if not accounts:
            raise RuntimeError(
                "Aucun compte options Deriv disponible pour ce broker account."
            )

        # 2. Sélectionner le compte selon le type configuré (demo / real)
        preferred_type = (
            getattr(self.broker_account, "deriv_account_type", None) or "demo"
        ).lower()
        selected = next(
            (a for a in accounts if str(a.get("account_type", "")).lower() == preferred_type),
            accounts[0],
        )
        account_id = selected.get("id") or selected.get("account_id")
        if not account_id:
            raise RuntimeError(
                f"Impossible de résoudre l'account_id Deriv depuis: {selected}"
            )

        # 3. OTP WebSocket URL (pré-authentifiée)
        ws_url = client.get_otp_ws_url_with_retry(str(account_id))

        # 4. Connexion et autorisation
        client.connect_with_otp_url(ws_url)
        client._send({"authorize": self.token})

        return client

    # ------------------------------------------------------------------
    # API contractuelle
    # ------------------------------------------------------------------
    def test_connection(self):
        try:
            ws_client = self._open_authenticated_ws()
            try:
                resp = ws_client.balance_ws(subscribe=0)
            finally:
                ws_client.close()
            balance = (resp or {}).get("balance") or {}
            return {
                "status": "ok",
                "broker": "DERIV",
                "loginid": balance.get("loginid"),
                "currency": balance.get("currency"),
            }
        except Exception as exc:
            log.exception(
                "deriv.test_connection.failed broker_account_id=%s",
                self.broker_account.id,
            )
            raise

    def fetch_balances(self):
        currency = self.broker_account.deriv_currency or "USD"

        try:
            ws_client = self._open_authenticated_ws()
            try:
                resp = ws_client.balance_ws(subscribe=0)
            finally:
                ws_client.close()
        except Exception as exc:
            log.warning(
                "deriv.fetch_balances.failed broker_account_id=%s err=%s",
                self.broker_account.id, exc,
            )
            raise

        payload = (resp or {}).get("balance") or {}
        total = _d(payload.get("balance"))
        return [
            BrokerBalanceDTO(
                currency=str(payload.get("currency") or currency),
                total=total,
                available=total,
                locked=Decimal("0"),
            )
        ]

    def fetch_positions(self):
        """
        Liste les contrats ouverts via portfolio_ws() puis demande le détail
        de chaque contract via proposal_open_contract.
        """
        positions: list[BrokerPositionDTO] = []
        try:
            ws_client = self._open_authenticated_ws()
            try:
                resp = ws_client.portfolio_ws()
                contracts = ((resp or {}).get("portfolio") or {}).get("contracts") or []
                for c in contracts:
                    contract_id = c.get("contract_id")
                    if not contract_id:
                        continue
                    contract_type = (c.get("contract_type") or "").upper()
                    side = "LONG" if contract_type.startswith("CALL") else "SHORT"
                    buy_price = _d(c.get("buy_price"))
                    positions.append(
                        BrokerPositionDTO(
                            symbol=str(c.get("symbol") or "DERIV"),
                            side=side,
                            quantity=Decimal("1"),
                            entry_price=buy_price,
                            current_price=_d(c.get("current_spot") or buy_price),
                            average_entry_price=buy_price,
                            leverage=Decimal("1"),
                            margin_used=buy_price,
                            broker_position_id=str(contract_id),
                            cost_basis_status="KNOWN" if buy_price > 0 else "UNKNOWN",
                            metadata=c,
                        )
                    )
            finally:
                ws_client.close()
        except Exception as exc:
            log.warning(
                "deriv.fetch_positions.failed broker_account_id=%s err=%s",
                self.broker_account.id, exc,
            )
            raise

        return positions

    def fetch_open_orders(self):
        # Deriv : pas d'order book, les "ordres" actifs sont les contrats.
        return []

    def fetch_order(self, order):
        from brokers.models_external_ref import BrokerExternalRef

        contract_id = order.broker_order_id
        if not contract_id:
            ref = BrokerExternalRef.objects.filter(
                broker="DERIV",
                broker_account=self.broker_account,
                internal_kind="ORDER",
                internal_id=str(order.id),
                kind="CONTRACT",
            ).first()
            contract_id = ref.external_id if ref else None
        if not contract_id:
            return None

        ws_client = self._open_authenticated_ws()
        try:
            response = ws_client.proposal_open_contract(contract_id=contract_id)
        finally:
            ws_client.close()

        contract = (response or {}).get("proposal_open_contract") or {}
        if not contract:
            return None

        buy_price = _d(contract.get("buy_price"))
        transaction_ids = contract.get("transaction_ids") or {}
        buy_transaction_id = transaction_ids.get("buy")
        fill_id = str(buy_transaction_id or f"buy:{contract_id}")

        BrokerExternalRef.upsert(
            broker="DERIV",
            broker_account=self.broker_account,
            kind="CONTRACT",
            external_id=str(contract_id),
            internal_kind="ORDER",
            internal_id=str(order.id),
            last_status=str(contract.get("status") or "open"),
            last_payload=contract,
        )

        return {
            # L'achat du contrat est un fill terminal de l'ordre d'ouverture;
            # le cycle de vie du contrat continue ensuite via BrokerExternalRef.
            "broker_order_id": str(contract_id),
            "broker_client_order_id": str(buy_transaction_id or ""),
            "symbol": contract.get("underlying") or contract.get("symbol") or order.symbol,
            "status": "FILLED",
            "fills": [{
                "broker_fill_id": fill_id,
                "quantity": Decimal("1"),
                "price": buy_price,
                "notional": buy_price,
                "fee": Decimal("0"),
                "fee_currency": order.portfolio.base_currency,
                "metadata": {
                    "deriv_contract_id": str(contract_id),
                    "recovered_by_reconciliation": True,
                },
            }],
            "raw": contract,
        }

    # ------------------------------------------------------------------
    # SUBMIT ORDER — envoi réel d'un ordre vers Deriv
    # ------------------------------------------------------------------
    def submit_order(self, order):
        """
        Envoie un BUY Deriv (option binaire). Renvoie un dict normalisé que
        l'orchestrator interprète :
            {
              "broker_order_id": "<contract_id>",
              "broker_client_order_id": "<transaction_id>",
              "status": "SUBMITTED",
              "fills": [
                  {"broker_fill_id": "<transaction_id>",
                   "quantity": "<qty>",
                   "price": "<buy_price>",
                   "notional": "<buy_price>",
                   "fee": "0"}
              ],
              "raw": {...payload Deriv...}
            }

        Effectue la séquence officielle Deriv :
          authorize → proposal → buy
        L'idempotency_key est passée comme `req_id` et stockée dans la metadata.
        """
        symbol = order.symbol
        amount = float(order.requested_stake_amount or order.approved_notional or 0)
        if amount <= 0:
            raise ValueError("Deriv submit : stake/notional doit être > 0.")

        contract_type = SIDE_TO_CONTRACT_TYPE.get(order.side, "CALL")
        if str(symbol).upper().startswith(("BOOM", "CRASH")):
            contract_type = SIDE_TO_MULTIPLIER_CONTRACT_TYPE.get(order.side, "MULTUP")
            duration = None
            duration_unit = None
            multiplier = int((order.metadata or {}).get("multiplier", 100))
        else:
            multiplier = None

        currency = (
            getattr(order.broker_account, "deriv_currency", None)
            or getattr(order.portfolio, "base_currency", None)
            or "USD"
        )
        duration = int(
            (order.metadata or {}).get("duration", 5)
        )
        duration_unit = (order.metadata or {}).get("duration_unit") or "s" # ticks par défaut

        ws_client = self._open_authenticated_ws()
        try:
            # 1. Proposal
            contracts = ws_client.contracts_for(order.symbol)
            logger.warning("DERIV_CONTRACTS_FOR symbol=%s data=%s", order.symbol, contracts)

            self._validate_deriv_contract_available(
                contracts_resp=contracts,
                symbol=order.symbol,
                contract_type=contract_type,
                duration_unit=duration_unit,
            )

            proposal_resp = ws_client.proposal(
                symbol=symbol,
                amount=amount,
                contract_type=contract_type,
                currency=currency,
                duration=duration,
                duration_unit=duration_unit,
                basis="stake",
                multiplier=multiplier,
            )
            proposal = proposal_resp.get("proposal") or {}
            proposal_id = proposal.get("id")
            if not proposal_id:
                raise RuntimeError(
                    f"Deriv proposal sans id : {proposal_resp}"
                )

            # 2. Buy
            buy_resp = ws_client.buy(
                proposal_id=proposal_id,
                price=amount,
            )
            buy = buy_resp.get("buy") or {}
            contract_id = buy.get("contract_id")
            tx_id = buy.get("transaction_id")
            buy_price = _d(buy.get("buy_price"))

            if not contract_id:
                raise RuntimeError(f"Deriv buy sans contract_id : {buy_resp}")

            # 3. Mapping interne ↔ broker — idempotent
            try:
                from brokers.models_external_ref import BrokerExternalRef
                BrokerExternalRef.upsert(
                    broker="DERIV",
                    broker_account=order.broker_account,
                    kind="CONTRACT",
                    external_id=str(contract_id),
                    internal_kind="ORDER",
                    internal_id=str(order.id),
                    last_status="open",
                    last_payload={
                        "buy_price": str(buy_price),
                        "transaction_id": tx_id,
                        "proposal_id": proposal_id,
                    },
                )
                if tx_id:
                    BrokerExternalRef.upsert(
                        broker="DERIV",
                        broker_account=order.broker_account,
                        kind="TRANSACTION",
                        external_id=str(tx_id),
                        internal_kind="ORDER",
                        internal_id=str(order.id),
                        last_status="bought",
                        last_payload={"contract_id": str(contract_id)},
                    )
            except Exception as exc:
                log.warning(
                    "deriv.submit_order.ref_upsert_failed order_id=%s err=%s",
                    order.id, exc,
                )

            log.info(
                "deriv.submit_order.ok order_id=%s contract_id=%s buy_price=%s",
                order.id, contract_id, buy_price,
            )

            # 4. Sync à la demande (5s) pour confirmer côté broker
            try:
                from brokers.tasks_deriv_sync import sync_single_deriv_contract_task
                sync_single_deriv_contract_task.apply_async(
                    args=(order.broker_account_id, str(contract_id)),
                    countdown=5,
                )
            except Exception:
                pass  # delay non bloquante

            # Convention Deriv (cf. _build_deriv_sizing) :
            #   - 1 contrat = 1 unité de position (quantity=1)
            #   - notional = stake = buy_price
            # On renvoie donc TOUJOURS quantity=1 pour que
            # FillProcessingService bascule l'ordre en FILLED dès que
            # filled_quantity >= approved_quantity (= 1).
            fill_quantity = Decimal("1")
            return {
                "broker_order_id": str(contract_id),
                "broker_client_order_id": str(tx_id) if tx_id else "",
                "status": "SUBMITTED",
                "fills": [
                    {
                        "broker_fill_id": str(tx_id) if tx_id else f"buy:{contract_id}",
                        "quantity": str(fill_quantity),
                        "price": str(buy_price),
                        "notional": str(buy_price),
                        "fee": "0",
                        "metadata": {
                            "deriv_contract_id": str(contract_id),
                            "deriv_proposal_id": str(proposal_id),
                        },
                    }
                ],
                "raw": {"proposal": proposal, "buy": buy},
            }
        finally:
            ws_client.close()

    def close_position(self, position, order):
        contract_id = position.broker_position_id or position.broker_order_id
        if not contract_id:
            raise ValueError(
                "Deriv contract_id manquant; fermeture automatique refusée."
            )
        if order.approved_quantity > position.quantity:
            raise ValueError("Deriv close quantity exceeds the target position.")

        ws_client = self._open_authenticated_ws()
        try:
            response = ws_client._send({
                "sell": int(contract_id),
                "price": 0,
            })
        finally:
            ws_client.close()

        sold = (response or {}).get("sell") or {}
        sold_for = _d(sold.get("sold_for"))
        transaction_id = sold.get("transaction_id") or sold.get("reference_id")
        quantity = _d(order.approved_quantity)
        fill_price = sold_for / quantity if quantity > 0 else Decimal("0")
        return {
            "broker_order_id": str(contract_id),
            "broker_client_order_id": str(transaction_id or ""),
            "status": "FILLED",
            "fills": [{
                "broker_fill_id": str(transaction_id or f"sell:{contract_id}"),
                "quantity": quantity,
                "price": fill_price,
                "notional": sold_for,
                "fee": Decimal("0"),
                "fee_currency": order.portfolio.base_currency,
                "metadata": {"deriv_contract_id": str(contract_id), **sold},
            }],
            "raw": response,
        }

    def cancel_order(self, order):
        """
        Pour Deriv, "annuler" = vendre le contrat avant échéance via sell().
        On résout le contract_id depuis BrokerExternalRef.
        """
        from brokers.models_external_ref import BrokerExternalRef
        ref = BrokerExternalRef.objects.filter(
            broker="DERIV",
            internal_kind="ORDER",
            internal_id=str(order.id),
            kind="CONTRACT",
        ).first()
        if not ref:
            raise RuntimeError(f"Aucun contract_id Deriv mappé pour order_id={order.id}")

        ws_client = self._open_authenticated_ws()
        try:
            resp = ws_client._send({
                "sell": int(ref.external_id),
                "price": 0,  # accepter le best price
            })
            sold = (resp or {}).get("sell") or {}
            log.info(
                "deriv.cancel_order.ok order_id=%s contract_id=%s sold_for=%s",
                order.id, ref.external_id, sold.get("sold_for"),
            )
            return {"status": "CANCELLED", "raw": resp}
        finally:
            ws_client.close()

    def fetch_symbol_constraints(self, symbol: str):
        return BrokerConstraintDTO(
            symbol=symbol,
            min_qty=Decimal("1"),
            max_qty=Decimal("100000"),
            qty_step=Decimal("1"),
            min_notional=Decimal("0"),
            price_tick=Decimal("0.01"),
            leverage_min=Decimal("1"),
            leverage_max=Decimal("1"),
            contract_size=Decimal("1"),
            raw_payload={},
        )
