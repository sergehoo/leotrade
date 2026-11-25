"""
brokers/services/deriv_sync.py
==============================

Handlers IDEMPOTENTS pour la synchronisation Deriv → DB.

Chaque handler est appelé soit :
  - depuis le worker WS persistant (deriv_streamer.py),
  - soit depuis les tâches Celery de fallback (brokers/tasks_deriv_sync.py).

Règles d'or :
- aucun handler ne crée de doublon : tout est ancré sur (broker, kind, external_id)
  via brokers.BrokerExternalRef ;
- aucun handler ne débite/crédite directement le portfolio : il délègue à
  PortfolioAccountingService/PositionCloseService pour le chemin canonique ou
  à DerivSettlementService pour les contrats historiques ;
- les erreurs sont loggées avec contexte structuré (broker_account_id,
  contract_id, internal_order_id) mais ne masquent jamais une exception
  qui doit remonter à l'appelant.

ARCHITECTURE DU DISPATCH on_open_contract_update
================================================
Priorité 1 : BrokerExternalRef → execution.models.Order         ← PATH CANONIQUE

Priorité 2 : trading.models.DerivContract trouvé par contract_id
             → DerivSettlementService.handle_contract_update()  ← HISTORIQUE

Priorité 3 : Contrat inconnu → _record_external_only_position() ← IMPORT EXTERNE
             (contrat ouvert directement sur deriv.com)
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction
from django.utils import timezone

from brokers.models import BrokerAccount
from brokers.models_external_ref import BrokerExternalRef
from execution.models import ExecutionFill, Order as ExecutionOrder
from portfolio.models import CashLedgerEntry, Portfolio, Position
from portfolio.services import PortfolioAccountingService, PortfolioService


log = logging.getLogger("leotrade.deriv.sync")


def _d(value, default: str = "0") -> Decimal:
    try:
        if value is None or value == "":
            return Decimal(default)
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _portfolio_for_broker_account(broker_account: BrokerAccount) -> Portfolio | None:
    """
    Retourne le portfolio principal lié à ce broker account (1-1 ou défaut).
    """
    return (
        Portfolio.objects
        .filter(broker_account=broker_account, is_active=True)
        .order_by("-is_default", "-created_at")
        .first()
    )


# =============================================================================
# 1. BALANCE
# =============================================================================

@transaction.atomic
def on_balance_update(broker_account_id: int, payload: dict[str, Any]) -> None:
    """
    Met à jour la balance du Portfolio à partir d'un événement broker.

    payload (Deriv balance event):
      {"balance": "1234.56", "currency": "USD", "loginid": "...", "id": "..."}

    Contrat :
    - on ne mute JAMAIS portfolio.current_balance directement ;
    - on calcule le delta entre la valeur Deriv et la balance interne calculée
      depuis le ledger, et on inscrit une ledger entry "BROKER_IMPORT" si non nul ;
    - clé d'idempotence = (broker, "BALANCE_SNAPSHOT", payload["id"] ou ts iso).
    """
    broker_account = BrokerAccount.objects.filter(pk=broker_account_id).first()
    if not broker_account:
        log.warning("on_balance_update: broker_account_id=%s introuvable", broker_account_id)
        return

    portfolio = _portfolio_for_broker_account(broker_account)
    if not portfolio:
        log.warning(
            "on_balance_update: aucun portfolio actif pour broker_account_id=%s",
            broker_account_id,
        )
        return

    remote_balance = _d(payload.get("balance"))
    snapshot_id = str(
        payload.get("id")
        or payload.get("loginid")
        or timezone.now().isoformat(timespec="seconds")
    )

    # Idempotence par snapshot
    if BrokerExternalRef.resolve(
        broker="DERIV",
        kind="TRANSACTION",
        external_id=f"balance_snapshot:{snapshot_id}",
    ):
        return

    portfolio = PortfolioService.recompute_cash_state(portfolio)

    # FIX SYNC : on compare la balance broker à la balance locale APRÈS avoir
    # remis le cash actuellement verrouillé par des ordres en vol.
    # Sans cette correction, pendant la fenêtre [lock_cash → register_fill]
    # on observe un faux delta positif (le broker n'a pas encore débité la
    # mise mais la lock l'a déjà fait localement), et un BROKER_IMPORT
    # fantôme est inséré au ledger — qui devra ensuite être manuellement
    # corrigé. Le broker reste source de vérité, le portfolio est miroir.
    locked_cash = (portfolio.locked_cash or Decimal("0")).quantize(Decimal("0.01"))
    adjusted_local_balance = (portfolio.current_balance + locked_cash).quantize(Decimal("0.01"))
    delta = (remote_balance - adjusted_local_balance).quantize(Decimal("0.01"))

    # Tolerance d'1 centime pour éviter les ajustements liés à l'arrondi.
    if abs(delta) >= Decimal("0.01"):
        PortfolioAccountingService.add_ledger_entry(
            portfolio=portfolio,
            entry_type="BROKER_IMPORT",
            amount=delta,
            currency=payload.get("currency") or portfolio.base_currency,
            reference_type="BROKER_BALANCE_SYNC",
            reference_id=snapshot_id,
            description="Ajustement automatique balance broker (Deriv)",
            metadata={
                "broker": "DERIV",
                "broker_account_id": broker_account.id,
                "remote_balance": str(remote_balance),
                "local_balance_before": str(portfolio.current_balance),
                "local_locked_cash": str(locked_cash),
                "adjusted_local_balance": str(adjusted_local_balance),
            },
        )
        log.info(
            "deriv.balance.adjusted portfolio_id=%s broker_account_id=%s delta=%s "
            "(locked_cash=%s)",
            portfolio.id, broker_account.id, delta, locked_cash,
        )

    BrokerExternalRef.upsert(
        broker="DERIV",
        broker_account=broker_account,
        kind="TRANSACTION",
        external_id=f"balance_snapshot:{snapshot_id}",
        internal_kind="ORDER",  # placeholder — la balance n'est liée à aucune entité interne
        internal_id=str(portfolio.id),
        last_status="OK",
        last_payload={"remote_balance": str(remote_balance)},
    )

    portfolio.last_reconciled_at = timezone.now()
    portfolio.save(update_fields=["last_reconciled_at", "updated_at"])


# =============================================================================
# 2. POSITIONS / OPEN CONTRACTS
# =============================================================================

@transaction.atomic
def on_open_contract_update(
    broker_account_id: int,
    payload: dict[str, Any],
) -> None:
    """
    Reçoit un payload ``proposal_open_contract`` Deriv et route vers le bon handler.

    payload (extrait Deriv) ::

        {
          "contract_id": 12345,
          "transaction_ids": {"buy": ..., "sell": ...},
          "buy_price": 10.0, "sell_price": 12.5, "profit": 2.5,
          "is_sold": 1, "is_settleable": 0,
          "status": "won|lost|sold|open",
          "currency": "USD",
          "underlying": "R_100",
        }

    PRIORITÉ DU DISPATCH
    --------------------
    1. BrokerExternalRef → execution.models.Order (CANONIQUE)

    2. trading.models.DerivContract trouvé par contract_id (HISTORIQUE)

    3. Contrat inconnu → import externe
       (contrat ouvert directement sur deriv.com sans passer par LeoTrade)
    """
    broker_account = BrokerAccount.objects.filter(pk=broker_account_id).first()
    if not broker_account:
        log.warning("on_open_contract_update: broker_account_id=%s introuvable", broker_account_id)
        return

    contract_id = payload.get("contract_id")
    if not contract_id:
        log.warning("on_open_contract_update: payload sans contract_id — %s", payload)
        return
    contract_id = str(contract_id)

    # ---------------------------------------------------------------
    # PATH 1 : Canonique — BrokerExternalRef → execution.models.Order
    # ---------------------------------------------------------------
    ref = BrokerExternalRef.resolve(
        broker="DERIV",
        kind="CONTRACT",
        external_id=contract_id,
    )

    exec_order: ExecutionOrder | None = None
    if ref and ref.internal_kind in ("ORDER", "EXECUTION_ORDER"):
        exec_order = ExecutionOrder.objects.filter(pk=ref.internal_id).first()

    if exec_order is not None:
        _handle_execution_order_update(
            order=exec_order,
            broker_account=broker_account,
            contract_id=contract_id,
            payload=payload,
        )
        return

    # ---------------------------------------------------------------
    # PATH 2 : Compatibilité historique — trading.DerivContract
    # ---------------------------------------------------------------
    try:
        from trading.models import DerivContract
        deriv_contract = DerivContract.objects.filter(
            contract_id=contract_id,
        ).select_related(
            "order__position", "portfolio", "broker_account",
        ).first()
    except Exception as exc:
        log.warning(
            "on_open_contract_update: erreur lookup DerivContract contract_id=%s err=%s",
            contract_id, exc,
        )
        deriv_contract = None

    if deriv_contract is not None:
        from trading.services.deriv_settlement import DerivSettlementService

        applied_status = DerivSettlementService.handle_contract_update(
            deriv_contract=deriv_contract,
            payload=payload,
        )
        BrokerExternalRef.upsert(
            broker="DERIV",
            broker_account=broker_account,
            kind="CONTRACT",
            external_id=contract_id,
            internal_kind="TRADING_ORDER",
            internal_id=str(deriv_contract.order_id),
            last_status=applied_status.lower(),
            last_payload={k: payload.get(k) for k in (
                "status", "is_sold", "is_settleable",
                "buy_price", "sell_price", "profit",
            )},
        )
        log.info(
            "deriv.contract.historical_path contract_id=%s applied_status=%s",
            contract_id, applied_status,
        )
        return

    # ---------------------------------------------------------------
    # PATH 3 : Contrat inconnu — importé comme position externe
    # ---------------------------------------------------------------
    log.info(
        "deriv.contract.unmapped contract_id=%s broker_account_id=%s — import externe",
        contract_id, broker_account_id,
    )
    _record_external_only_position(broker_account, payload)


def _handle_execution_order_update(
    *,
    order: ExecutionOrder,
    broker_account: BrokerAccount,
    contract_id: str,
    payload: dict,
) -> None:
    """
    Met à jour un execution.Order canonique et crée un ExecutionFill
    de clôture quand Deriv signale is_sold / is_settleable.
    """
    new_status, broker_status_str = _map_deriv_status_to_execution_order(payload)
    if new_status and order.status != new_status:
        order.status = new_status
        if new_status == "FILLED" and not getattr(order, "filled_at", None):
            order.filled_at = timezone.now()
        order.save(update_fields=["status", "filled_at", "updated_at"])

    is_closed = _is_deriv_terminal(payload)
    if is_closed:
        sell_tx_id = (payload.get("transaction_ids") or {}).get("sell")
        sell_external_id = str(sell_tx_id) if sell_tx_id else f"contract_close:{contract_id}"

        if not BrokerExternalRef.resolve(
            broker="DERIV",
            kind="TRANSACTION",
            external_id=sell_external_id,
        ):
            _record_closing_fill_for_execution_order(
                order=order,
                broker_account=broker_account,
                contract_id=contract_id,
                sell_external_id=sell_external_id,
                payload=payload,
            )

    order.metadata = {
        **(order.metadata or {}),
        "deriv_contract_status": broker_status_str,
        "deriv_contract_profit": str(_d(payload.get("profit"))),
    }
    order.save(update_fields=["metadata", "updated_at"])

    BrokerExternalRef.upsert(
        broker="DERIV",
        broker_account=broker_account,
        kind="CONTRACT",
        external_id=contract_id,
        internal_kind="ORDER",
        internal_id=str(order.id),
        last_status=broker_status_str,
        last_payload={k: payload.get(k) for k in (
            "status", "is_sold", "is_settleable", "buy_price", "sell_price", "profit",
        )},
    )


def _map_deriv_status_to_execution_order(payload: dict) -> tuple[str | None, str]:
    """
    Traduit (is_sold/is_settleable/status) Deriv vers les statuts d'execution.Order.
    Retourne (status_interne, status_broker_str).
    """
    status = (payload.get("status") or "").lower()
    is_sold = bool(payload.get("is_sold"))
    is_settleable = bool(payload.get("is_settleable"))

    if is_sold or is_settleable or status in ("won", "lost", "sold", "expired", "cancelled"):
        return "FILLED", status or "closed"
    if status in ("open", "running"):
        return "SUBMITTED", status

    return None, status or "unknown"


def _is_deriv_terminal(payload: dict) -> bool:
    status = str(payload.get("status") or "").lower()
    return bool(
        payload.get("is_sold")
        or payload.get("is_settleable")
        or status in {"won", "lost", "sold", "expired", "cancelled"}
    )


def _record_closing_fill_for_execution_order(
    *,
    order: ExecutionOrder,
    broker_account: BrokerAccount,
    contract_id: str,
    sell_external_id: str,
    payload: dict,
) -> ExecutionFill:
    """
    Crée un ExecutionFill pour la sortie d'un contrat Deriv
    associé à un execution.Order (orchestre d'exécution générique).
    """
    sell_price = _d(payload.get("sell_price"))
    profit = _d(payload.get("profit"))

    qty_field = (
        getattr(order, "approved_quantity", None)
        or getattr(order, "requested_quantity", None)
        or Decimal("1")
    )

    fill = ExecutionFill.objects.create(
        order=order,
        broker_fill_id=sell_external_id,
        quantity=qty_field,
        price=sell_price,
        notional=sell_price,
        fee=Decimal("0"),
        fee_currency=payload.get("currency") or "USD",
        fill_time=timezone.now(),
        liquidity_type="CLOSE",
        metadata={
            "deriv_contract_id": contract_id,
            "profit": str(profit),
        },
    )

    BrokerExternalRef.upsert(
        broker="DERIV",
        broker_account=broker_account,
        kind="TRANSACTION",
        external_id=sell_external_id,
        internal_kind="EXECUTION_FILL",
        internal_id=str(fill.id),
        last_status="closed",
        last_payload={"sell_price": str(sell_price), "profit": str(profit)},
    )

    try:
        from execution.services_close import PositionCloseService
        PositionCloseService.apply_deriv_contract_settlement(
            opening_order=order,
            fill=fill,
            profit=profit,
        )
    except Exception as exc:
        log.exception(
            "deriv.close.position.failed order_id=%s contract_id=%s err=%s",
            order.id, contract_id, exc,
        )

    log.info(
        "deriv.contract.closed order_id=%s contract_id=%s profit=%s",
        order.id, contract_id, profit,
    )
    return fill


def _record_external_only_position(
    broker_account: BrokerAccount,
    payload: dict,
) -> None:
    """
    Cas où un contrat est créé hors LeoTrade. On crée une Position importée
    pour visibilité, mais sans débit cash (ces opérations ont été faites côté broker).
    """
    portfolio = _portfolio_for_broker_account(broker_account)
    if not portfolio:
        return

    contract_id = str(payload.get("contract_id"))

    # Pour les contrats Deriv, la "quantité" est la mise engagée (buy_price).
    # La valeur 1 était fausse : elle cassait les calculs de P&L et de notional.
    buy_price = _d(payload.get("buy_price"))
    quantity = buy_price if buy_price > Decimal("0") else Decimal("1")
    contract_type = (payload.get("contract_type") or "").upper()
    side = "LONG" if (contract_type.startswith("CALL") or contract_type == "BUY") else "SHORT"

    pos, created = Position.objects.update_or_create(
        portfolio=portfolio,
        broker_position_id=contract_id,
        defaults={
            "broker_account": broker_account,
            "symbol": payload.get("underlying") or "DERIV",
            "asset_name": payload.get("display_name") or payload.get("shortcode") or "",
            "side": side,
            "quantity": quantity,
            "entry_price": buy_price,
            "current_price": _d(payload.get("current_spot") or payload.get("bid_price") or payload.get("buy_price")),
            "average_entry_price": buy_price,
            "notional_value": buy_price,
            "exposure_value": buy_price,
            "status": "CLOSED" if payload.get("is_sold") else "OPEN",
            "source": "IMPORTED",
            "cost_basis_status": "ESTIMATED",
            "metadata": {"deriv_external_only": True, "raw": payload},
        },
    )
    if created:
        log.info(
            "deriv.position.imported_external contract_id=%s portfolio_id=%s",
            contract_id, portfolio.id,
        )


# =============================================================================
# 3. TRANSACTION (cash mvts unitaires)
# =============================================================================

@transaction.atomic
def on_transaction(broker_account_id: int, payload: dict[str, Any]) -> None:
    """
    Reçoit un événement `transaction` Deriv (achat, vente, ajustement, deposit, withdrawal).
    Idempotence par transaction_id. À utiliser comme tracking secondaire.
    """
    broker_account = BrokerAccount.objects.filter(pk=broker_account_id).first()
    if not broker_account:
        return

    tx_id = payload.get("transaction_id") or payload.get("id")
    if not tx_id:
        return

    if BrokerExternalRef.resolve(
        broker="DERIV",
        kind="TRANSACTION",
        external_id=str(tx_id),
    ):
        return

    portfolio = _portfolio_for_broker_account(broker_account)
    if not portfolio:
        return

    BrokerExternalRef.upsert(
        broker="DERIV",
        broker_account=broker_account,
        kind="TRANSACTION",
        external_id=str(tx_id),
        internal_kind="ORDER",  # liaison best-effort
        internal_id=str(payload.get("contract_id") or "0"),
        last_status=payload.get("action") or "tx",
        last_payload=payload,
    )

    log.info(
        "deriv.tx.recorded broker_account_id=%s tx_id=%s action=%s amount=%s",
        broker_account_id, tx_id, payload.get("action"), payload.get("amount"),
    )
