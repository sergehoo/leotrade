"""
trading/services/deriv_settlement.py
=====================================

DerivSettlementService : règlement complet d'un contrat Deriv à sa clôture.

FLUX APPLIQUÉ
=============
1. Lyneci achète le contrat  → DerivContract(status=OPEN) créé,
                                  Position ouverte,
                                  -buy_price débité du Portfolio (TRADE_EXECUTION)

2. Deriv dit won / lost / sold / expired
   → on_open_contract_update()  appelle DerivSettlementService.handle_contract_update()

3. DerivSettlementService._settle() :
   a. Marque DerivContract.status  = WON / LOST / SOLD / EXPIRED
   b. Ferme la Position liée       (status=CLOSED, realized_pnl=profit)
   c. Crée le Trade (round-trip)   (source de vérité PnL)
   d. Crédite le Portfolio         +sell_price si sell_price > 0  (WON / SOLD)
      → pour LOST : sell_price = 0, aucun crédit nécessaire
        (le buy_price avait déjà réduit la balance à l'ouverture)
   e. Rafraîchit les métriques     portfolio.equity / unrealized / drawdown

COMPTABILITÉ DE TRÉSORERIE
==========================
Ouverture :  TRADE_EXECUTION  –buy_price    (écriture OMS canonique)
Clôture WON: TRADE_EXECUTION  +sell_price   (sell_price > buy_price → profit)
Clôture LOST: rien            (sell_price=0, balance déjà correcte)
Clôture SOLD: TRADE_EXECUTION +sell_price   (vente anticipée, peut être < buy_price)

Balance nette = starting_balance – buy_price + sell_price = starting_balance + profit ✓

IDEMPOTENCE
===========
Toutes les opérations sont gardées par :
- DerivContract.status ∈ TERMINAL_STATUSES → on n'applique pas deux fois le règlement
- CashLedgerEntry.filter(reference_type="DERIV_CONTRACT", reference_id=..., entry_type="TRADE_EXECUTION", amount__gt=0)
  → on ne crédite pas deux fois

NOTE : Trade.opening_order et Trade.closing_fill sont NULL pour les contrats Deriv
(ces FK pointent vers execution.Order / execution.ExecutionFill, or les contrats
Deriv utilisent trading.Order). Les infos de traçabilité sont dans Trade.metadata.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from portfolio.models import CashLedgerEntry, Position
from portfolio.models_trade import Trade
from portfolio.services import PortfolioAccountingService, PortfolioService
from trading.models import DerivContract


log = logging.getLogger("lyneci.trading.settlement")


def _d(value, default: str = "0") -> Decimal:
    """Conversion sûre vers Decimal."""
    try:
        if value is None or value == "":
            return Decimal(default)
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


# --------------------------------------------------------------------------
# Mapping Deriv status → DerivContract status
# --------------------------------------------------------------------------

_DERIV_STATUS_MAP: dict[str, str] = {
    "won":     "WON",
    "lost":    "LOST",
    "sold":    "SOLD",
    "expired": "EXPIRED",
    "open":    "OPEN",
    "running": "OPEN",
}

TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"WON", "LOST", "SOLD", "EXPIRED", "CANCELLED", "FAILED"}
)


class DerivSettlementService:
    """
    Service de règlement d'un contrat Deriv.
    Appelé depuis brokers.services.deriv_sync.on_open_contract_update().
    """

    @staticmethod
    @transaction.atomic
    def handle_contract_update(
        deriv_contract: DerivContract,
        payload: dict,
    ) -> str:
        """
        Point d'entrée principal.

        :param deriv_contract: instance DerivContract existante
        :param payload:        payload ``proposal_open_contract`` de Deriv
        :returns: le statut appliqué (ex. "OPEN", "WON", "LOST", "SOLD", "EXPIRED")
        """
        raw_status  = (payload.get("status") or "").lower()
        is_sold     = bool(payload.get("is_sold"))
        is_settleable = bool(payload.get("is_settleable"))

        # --- Déterminer le nouveau statut --------------------------------
        if is_sold:
            new_status = "SOLD"
        elif is_settleable:
            # is_settleable=1 avec status="won" ou "lost"
            new_status = _DERIV_STATUS_MAP.get(raw_status, "WON")
            if new_status == "OPEN":
                new_status = "WON"
        else:
            new_status = _DERIV_STATUS_MAP.get(raw_status, "OPEN")

        # Toujours mettre à jour le dernier payload broker
        deriv_contract.latest_contract_payload = payload

        if new_status in TERMINAL_STATUSES:
            if deriv_contract.status in TERMINAL_STATUSES:
                # Déjà réglé — on rafraîchit juste le payload
                deriv_contract.save(update_fields=["latest_contract_payload", "updated_at"])
                log.debug(
                    "deriv.settlement.already_settled contract_id=%s status=%s",
                    deriv_contract.contract_id, deriv_contract.status,
                )
            else:
                # Règlement terminal
                DerivSettlementService._settle(deriv_contract, payload, new_status)
        else:
            # Contrat encore ouvert — mise à jour live tick si disponible
            entry_tick = payload.get("entry_tick") or payload.get("entry_spot")
            if entry_tick:
                deriv_contract.entry_tick = _d(entry_tick)
            deriv_contract.save(update_fields=[
                "latest_contract_payload", "entry_tick", "updated_at",
            ])

        return new_status

    # ------------------------------------------------------------------

    @staticmethod
    def _settle(
        deriv_contract: DerivContract,
        payload: dict,
        new_status: str,
    ) -> None:
        """
        Règlement atomique du contrat.
        Appelé dans le contexte @transaction.atomic du parent.
        """
        profit      = _d(payload.get("profit"))
        sell_price  = _d(payload.get("sell_price"))
        exit_tick   = _d(payload.get("exit_tick") or payload.get("exit_spot") or 0)
        buy_price   = _d(deriv_contract.buy_price)
        currency    = payload.get("currency") or deriv_contract.currency or "USD"

        # --- 1. Mettre à jour le DerivContract --------------------------
        deriv_contract.status     = new_status
        deriv_contract.profit     = profit
        deriv_contract.payout     = sell_price
        deriv_contract.exit_tick  = exit_tick if exit_tick > Decimal("0") else None
        deriv_contract.is_sold    = bool(payload.get("is_sold"))
        deriv_contract.is_expired = (new_status == "EXPIRED")
        deriv_contract.settled_at = timezone.now()
        deriv_contract.save(update_fields=[
            "status", "profit", "payout", "exit_tick",
            "is_sold", "is_expired", "settled_at",
            "latest_contract_payload", "updated_at",
        ])

        # --- 2. Mettre à jour l'Order trading ---------------------------
        order = deriv_contract.order
        if order and order.status not in ("FILLED", "CANCELLED", "REJECTED", "FAILED"):
            order.status    = "FILLED"
            order.filled_at = timezone.now()
            order.save(update_fields=["status", "filled_at", "updated_at"])

        # --- 3. Fermer la Position --------------------------------------
        portfolio = deriv_contract.portfolio
        position: Position | None = getattr(order, "position", None) if order else None

        trade: Trade | None = None

        if position and position.status in ("OPEN", "PARTIALLY_CLOSED"):
            # Verrou pessimiste pour éviter double-clôture concurrente
            position = Position.objects.select_for_update().get(pk=position.pk)

            if position.status in ("OPEN", "PARTIALLY_CLOSED"):
                closing_qty = _d(position.quantity) if _d(position.quantity) > 0 else Decimal("1")
                entry_avg   = _d(position.average_entry_price or position.entry_price or 0)
                realized_pnl = profit.quantize(Decimal("0.01"))

                # --- 4. Créer le Trade (round-trip clos) ----------------
                trade = Trade.objects.create(
                    portfolio       = portfolio,
                    position        = position,
                    broker_account  = deriv_contract.broker_account,
                    broker_fill_id  = str(deriv_contract.contract_id),
                    closing_fill    = None,    # pas d'ExecutionFill pour Deriv
                    opening_order   = None,    # trading.Order ≠ execution.Order
                    symbol          = deriv_contract.symbol,
                    side            = position.side,
                    quantity        = closing_qty,
                    entry_avg_price = entry_avg,
                    exit_avg_price  = sell_price,
                    gross_pnl       = profit.quantize(Decimal("0.01")),
                    fees            = Decimal("0.00"),
                    realized_pnl    = realized_pnl,
                    cash_invested   = buy_price.quantize(Decimal("0.01")),
                    cash_returned   = sell_price.quantize(Decimal("0.01")),
                    opened_at       = position.opened_at,
                    closed_at       = timezone.now(),
                    metadata        = {
                        "deriv_contract_id" : deriv_contract.contract_id,
                        "deriv_status"      : new_status,
                        "contract_type"     : deriv_contract.contract_type,
                        "trading_order_id"  : order.id if order else None,
                        "buy_price"         : str(buy_price),
                        "sell_price"        : str(sell_price),
                        "broker_profit"     : str(profit),
                        "payload_status"    : payload.get("status"),
                        "is_sold"           : bool(payload.get("is_sold")),
                        "is_settleable"     : bool(payload.get("is_settleable")),
                    },
                )

                # Mettre à jour la Position
                position.quantity     = Decimal("0")
                position.status       = "CLOSED"
                position.closed_at    = timezone.now()
                position.realized_pnl = realized_pnl
                position.save(update_fields=[
                    "quantity", "status", "closed_at", "realized_pnl", "updated_at",
                ])

                log.info(
                    "deriv.settle.position_closed position_id=%s trade_id=%s pnl=%s contract=%s",
                    position.id, trade.id, realized_pnl, new_status,
                )
        else:
            log.warning(
                "deriv.settle.no_open_position contract_id=%s order_id=%s — trade non créé",
                deriv_contract.contract_id,
                order.id if order else None,
            )

        # --- 5. Écriture ledger : créditer le payout reçu ---------------
        #
        # COMPTABILITÉ :
        #   Ouverture → TRADE_EXECUTION -buy_price   (écriture OMS canonique)
        #   Clôture WON/SOLD → TRADE_EXECUTION +sell_price
        #   Clôture LOST/EXPIRED → sell_price = 0, pas d'écriture
        #   Solde net = -buy_price + sell_price = profit  ✓
        #
        if sell_price > Decimal("0"):
            # Idempotence : pas de double crédit
            already_credited = CashLedgerEntry.objects.filter(
                portfolio      = portfolio,
                reference_type = "DERIV_CONTRACT",
                reference_id   = str(deriv_contract.id),
                entry_type     = "TRADE_EXECUTION",
                amount__gt     = Decimal("0"),
            ).exists()

            if not already_credited:
                PortfolioAccountingService.add_ledger_entry(
                    portfolio      = portfolio,
                    entry_type     = "TRADE_EXECUTION",
                    amount         = sell_price,
                    currency       = currency,
                    reference_type = "DERIV_CONTRACT",
                    reference_id   = str(deriv_contract.id),
                    description    = (
                        f"Règlement Deriv #{deriv_contract.contract_id} "
                        f"{deriv_contract.symbol} → {new_status} "
                        f"(profit {profit:+.2f} {currency})"
                    ),
                    metadata       = {
                        "deriv_contract_id" : deriv_contract.contract_id,
                        "status"            : new_status,
                        "buy_price"         : str(buy_price),
                        "sell_price"        : str(sell_price),
                        "profit"            : str(profit),
                        "trade_id"          : trade.id if trade else None,
                    },
                )
        else:
            # LOST / EXPIRED avec payout = 0 → la balance est déjà correcte
            # (buy_price avait été débité à l'ouverture, rien à restituer)
            log.info(
                "deriv.settle.no_payout contract_id=%s status=%s buy_price=%s",
                deriv_contract.contract_id, new_status, buy_price,
            )

        # --- 6. Rafraîchir les métriques portfolio ----------------------
        PortfolioService.refresh_portfolio_metrics(portfolio)

        log.info(
            "deriv.settlement.complete contract_id=%s status=%s profit=%s "
            "sell_price=%s buy_price=%s portfolio_id=%s",
            deriv_contract.contract_id, new_status,
            profit, sell_price, buy_price, portfolio.id,
        )
