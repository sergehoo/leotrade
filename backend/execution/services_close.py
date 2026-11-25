"""
execution/services_close.py
===========================

PositionCloseService : applique un fill de fermeture (totale ou partielle)
sur une Position et crée le Trade correspondant (round-trip clos).

Règles :
- Toute écriture est atomique avec select_for_update sur Position ;
- realized_pnl du Trade est CALCULÉ ici (formule canonique) :
      LONG :  (exit - entry) * qty - fees
      SHORT : (entry - exit) * qty - fees
- Une seule ligne `TRADE_EXECUTION` est ajoutée au CashLedger pour le delta net
  de la fermeture, AUCUNE entrée `PNL_REALIZED` séparée n'est créée
  (sinon double-comptage avec Trade.realized_pnl).

Ce service est appelé :
- par execution.FillProcessingService quand un fill *réduit* une position ;
- par brokers.services.deriv_sync.on_open_contract_update quand Deriv signale
  is_sold/is_settleable ;
- manuellement depuis le manager admin pour clôturer une position orpheline.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from execution.models import ExecutionFill, Order
from portfolio.models import Position
from portfolio.models_trade import Trade
from portfolio.services import PortfolioAccountingService, PortfolioService


log = logging.getLogger("leotrade.execution.close")


class PositionCloseError(Exception):
    pass


class PositionCloseService:

    @staticmethod
    @transaction.atomic
    def apply_deriv_contract_settlement(
        *,
        opening_order: Order,
        fill: ExecutionFill,
        profit: Decimal,
    ) -> Trade | None:
        """Close the position opened by a settled Deriv contract."""
        expected_side = "LONG" if opening_order.side == "BUY" else "SHORT"
        positions = (
            Position.objects
            .select_for_update()
            .filter(
                portfolio=opening_order.portfolio,
                broker_account=opening_order.broker_account,
                symbol=opening_order.symbol,
                side=expected_side,
                status__in=["OPEN", "PARTIALLY_CLOSED"],
            )
        )
        position = positions.filter(
            broker_order_id=opening_order.broker_order_id,
        ).first()
        if position is None:
            position = positions.order_by("opened_at").first()
        if position is None:
            log.warning(
                "deriv.close.no_open_position order_id=%s symbol=%s portfolio_id=%s",
                opening_order.id,
                opening_order.symbol,
                opening_order.portfolio_id,
            )
            return None

        return PositionCloseService.apply_closing_fill(
            position=position,
            fill=fill,
            opening_order=opening_order,
            override_profit=profit,
        )

    @staticmethod
    @transaction.atomic
    def apply_closing_fill_for_order(
        *,
        order: Order,
        fill: ExecutionFill,
        profit: Decimal | None = None,
    ) -> Trade | None:
        """
        Cas 1 : on a un Order interne (cycle normal LeoTrade).
        Trouve la Position liée et applique la clôture.

        :param profit: pour Deriv (option binaire), profit fourni directement
                       par le payload broker. Si absent, calculé.
        """
        target_position_id = (
            order.closes_position_id
            or (order.metadata or {}).get("closes_position_id")
        )
        expected_side = "SHORT" if order.side == "BUY" else "LONG"
        positions = (
            Position.objects
            .select_for_update()
            .filter(
                portfolio=order.portfolio,
                symbol=order.symbol,
                side=expected_side,
                status__in=["OPEN", "PARTIALLY_CLOSED"],
            )
        )
        if target_position_id:
            positions = positions.filter(pk=target_position_id)
        position = positions.order_by("opened_at").first()
        if not position:
            log.warning(
                "close.no_open_position order_id=%s symbol=%s portfolio_id=%s",
                order.id, order.symbol, order.portfolio_id,
            )
            return None

        return PositionCloseService.apply_closing_fill(
            position=position,
            fill=fill,
            opening_order=order,
            override_profit=profit,
        )

    @staticmethod
    @transaction.atomic
    def apply_closing_fill(
        *,
        position: Position,
        fill: ExecutionFill,
        opening_order: Order | None = None,
        override_profit: Decimal | None = None,
    ) -> Trade:
        """
        Applique fill de clôture. Crée un Trade. Met à jour la position.
        Inscrit la ligne TRADE_EXECUTION nette dans le ledger.

        Si fill.quantity >= position.quantity → fermeture totale.
        Sinon → fermeture partielle.
        """
        # Verrou sur la position
        position = Position.objects.select_for_update().get(pk=position.pk)

        if position.status not in ("OPEN", "PARTIALLY_CLOSED"):
            raise PositionCloseError(
                f"Position {position.id} status={position.status} non clôturable"
            )

        closing_qty = min(
            Decimal(str(fill.quantity or 0)),
            Decimal(str(position.quantity or 0)),
        )
        if closing_qty <= 0:
            raise PositionCloseError("closing_qty <= 0")

        exit_price = Decimal(str(fill.price or 0))
        entry_avg = Decimal(str(position.average_entry_price or position.entry_price or 0))
        fees = Decimal(str(fill.fee or 0))

        if override_profit is not None:
            # Cas Deriv : on prend la valeur fournie par le broker (option binaire)
            gross_pnl = Decimal(str(override_profit))
        else:
            sign = Decimal("1") if position.side == "LONG" else Decimal("-1")
            gross_pnl = (exit_price - entry_avg) * closing_qty * sign

        realized_pnl = (gross_pnl - fees).quantize(Decimal("0.01"))
        cash_invested = (entry_avg * closing_qty).quantize(Decimal("0.01"))
        # cash_returned = ce qui revient au portfolio = capital initial + PnL net
        cash_returned = (cash_invested + realized_pnl).quantize(Decimal("0.01"))

        # 1. Crée le Trade (round-trip clos)
        trade = Trade.objects.create(
            portfolio=position.portfolio,
            position=position,
            broker_account=position.broker_account,
            broker_fill_id=fill.broker_fill_id,
            closing_fill=fill,
            opening_order=opening_order,
            symbol=position.symbol,
            side=position.side,
            quantity=closing_qty,
            entry_avg_price=entry_avg,
            exit_avg_price=exit_price,
            gross_pnl=gross_pnl.quantize(Decimal("0.01")),
            fees=fees,
            realized_pnl=realized_pnl,
            cash_invested=cash_invested,
            cash_returned=cash_returned,
            opened_at=position.opened_at,
            closed_at=timezone.now(),
            metadata={
                "fill_id": fill.id,
                "override_profit": str(override_profit) if override_profit is not None else None,
            },
        )

        # 2. Met à jour la Position
        new_qty = (Decimal(str(position.quantity)) - closing_qty).quantize(Decimal("0.00000001"))
        position.quantity = new_qty
        position.realized_pnl = (Decimal(str(position.realized_pnl or 0)) + realized_pnl).quantize(Decimal("0.01"))

        if new_qty <= 0:
            position.quantity = Decimal("0")
            position.status = "CLOSED"
            position.closed_at = timezone.now()
        else:
            position.status = "PARTIALLY_CLOSED"

        position.save(update_fields=[
            "quantity", "realized_pnl", "status", "closed_at", "updated_at",
        ])

        if position.status == "CLOSED":
            from execution.protection import PositionProtectionService
            PositionProtectionService.mark_completed(position)

        # 3. Inscription cash : delta net (cash_returned ou positif PnL si Deriv binary)
        # On utilise TRADE_EXECUTION comme entry_type (à étendre dans ENTRY_TYPE_CHOICES si besoin).
        # Pour Deriv (option binaire), pas de "release lock" car le stake était directement débité.
        # On crédite simplement le portfolio du sell_price (ou cash_returned).
        if cash_returned != Decimal("0"):
            PortfolioAccountingService.add_ledger_entry(
                portfolio=position.portfolio,
                entry_type="MANUAL_ADJUSTMENT" if not _has_trade_execution_type() else "TRADE_EXECUTION",
                amount=cash_returned,
                reference_type="TRADE",
                reference_id=str(trade.id),
                description=f"Clôture {position.symbol} qty={closing_qty} @ {exit_price}",
                metadata={
                    "trade_id": trade.id,
                    "position_id": position.id,
                    "realized_pnl": str(realized_pnl),
                    "gross_pnl": str(gross_pnl),
                    "fees": str(fees),
                },
            )

        # 4. Refresh metrics du portfolio (cache UI)
        PortfolioService.refresh_portfolio_metrics(position.portfolio)

        log.info(
            "close.position.ok position_id=%s closing_qty=%s realized_pnl=%s status=%s trade_id=%s",
            position.id, closing_qty, realized_pnl, position.status, trade.id,
        )

        # Notification multicanale — PnL réel du round-trip
        try:
            from notifications.shortcuts import notify

            owner = getattr(position.portfolio, "user", None)
            outcome = "gagnante 🎯" if realized_pnl > 0 else ("perdante" if realized_pnl < 0 else "à l'équilibre")
            full_close = position.status == "CLOSED"
            notify(
                owner, "POSITION_CLOSED",
                title=(
                    f"Position {'fermée' if full_close else 'réduite'} : "
                    f"{position.symbol} ({realized_pnl:+.2f})"
                ),
                message=(
                    f"Clôture {'totale' if full_close else 'partielle'} {outcome} "
                    f"de {position.symbol} : {closing_qty} @ {exit_price}, "
                    f"PnL réalisé {realized_pnl:+.2f}."
                ),
                payload={
                    "position_id": position.id,
                    "trade_id": trade.id,
                    "symbol": position.symbol,
                    "realized_pnl": str(realized_pnl),
                    "full_close": full_close,
                },
            )
        except Exception:
            log.exception("close.position.notify_failed position_id=%s", position.id)
        return trade


def _has_trade_execution_type() -> bool:
    """
    Compatibilité : si "TRADE_EXECUTION" n'est pas dans ENTRY_TYPE_CHOICES
    de CashLedgerEntry, on retombe sur "MANUAL_ADJUSTMENT".
    Ajoute "TRADE_EXECUTION" dans CashLedgerEntry.ENTRY_TYPE_CHOICES via PATCH_PHASE3.
    """
    from portfolio.models import CashLedgerEntry
    types = {t for t, _ in CashLedgerEntry.ENTRY_TYPE_CHOICES}
    return "TRADE_EXECUTION" in types
