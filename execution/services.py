# /Users/ogahserge/Documents/leoTrade/execution/services.py
from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import uuid4, UUID

from django.db import transaction, DatabaseError
from django.db.transaction import TransactionManagementError
from django.utils import timezone

from core.logging import get_logger, log_event
from portfolio.models import Position
from portfolio.services import PortfolioAccountingService, PortfolioService
from .models import Order, ExecutionFill, ExecutionEvent
from .adapters.factory import BrokerAdapterFactory
from core.realtime import RealtimeBroadcastService
from execution.notifications import TradingNotificationService
from risk.services import RiskGuardService, RiskDecisionService

logger = get_logger("execution")

PRICE_PRECISION = Decimal("0.00000001")


def q8(value):
    try:
        if value is None:
            return None
        return Decimal(str(value)).quantize(PRICE_PRECISION, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return None


def _d(value, default="0"):
    try:
        if value is None:
            return Decimal(default)
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _json_safe(value):
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, UUID):
        return str(value)

    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]

    if hasattr(value, "_asdict"):
        return _json_safe(value._asdict())

    return str(value)


class ExecutionEventService:
    @staticmethod
    def log(order: Order, event_type: str, message: str = "", payload: dict | None = None):
        """
        Persist an execution event and broadcast it.

        FIX: broadcast is now scheduled with ``transaction.on_commit`` so the
        frontend never sees an event for a DB state that ends up rolled back.
        """
        safe_payload = _json_safe(payload or {})

        event = ExecutionEvent.objects.create(
            order=order,
            event_type=event_type,
            message=message,
            payload=safe_payload,
            created_by_system=True,
        )

        broadcast_payload = {
            "kind": "event",
            "order_id": order.id,
            "event_type": event_type,
            "message": message,
            "payload": safe_payload,
            "created_at": event.created_at.isoformat(),
        }

        def _broadcast():
            RealtimeBroadcastService.broadcast_order_update(
                user_id=order.user_id,
                payload=broadcast_payload,
            )

        try:
            transaction.on_commit(_broadcast)
        except TransactionManagementError:
            # Outside any transaction — broadcast immediately.
            _broadcast()

        return event


class OrderLifecycleService:
    @staticmethod
    def mark_submitted(order: Order, payload: dict):
        safe_payload = _json_safe(payload or {})

        order.status = "SUBMITTED"
        order.broker_order_id = safe_payload.get("broker_order_id") or order.broker_order_id
        order.broker_client_order_id = safe_payload.get("broker_client_order_id") or order.broker_client_order_id
        order.submitted_at = safe_payload.get("submitted_at") or timezone.now()
        order.metadata = {
            **(order.metadata or {}),
            "submit_payload": safe_payload.get("raw", safe_payload),
        }

        TradingNotificationService.notify_order_submitted(order)
        order.save(update_fields=[
            "status",
            "broker_order_id",
            "broker_client_order_id",
            "submitted_at",
            "metadata",
            "updated_at",
        ])
        ExecutionEventService.log(order, "ORDER_SUBMITTED", "Ordre soumis au broker.", safe_payload)

    @staticmethod
    def mark_cancelled(order: Order, payload: dict | None = None):
        order.status = "CANCELLED"
        order.cancelled_at = timezone.now()
        order.save(update_fields=["status", "cancelled_at", "updated_at"])
        TradingNotificationService.notify_order_cancelled(order)
        ExecutionEventService.log(order, "ORDER_CANCELLED", "Ordre annulé.", payload or {})

    @staticmethod
    def mark_rejected(order: Order, message: str, payload: dict | None = None):
        order.status = "REJECTED"
        order.rejected_at = timezone.now()
        order.execution_notes = message
        order.save(update_fields=["status", "rejected_at", "execution_notes", "updated_at"])
        TradingNotificationService.notify_error(
            user_id=order.user_id,
            message=message,
            payload={"order_id": order.id, "symbol": order.symbol},
        )
        ExecutionEventService.log(order, "ORDER_REJECTED", message, payload or {})

    @staticmethod
    def mark_failed(order: Order, message: str, payload: dict | None = None):
        order.status = "FAILED"
        order.execution_notes = message
        TradingNotificationService.notify_error(
            user_id=order.user_id,
            message=message,
            payload={"order_id": order.id, "symbol": order.symbol},
        )
        order.save(update_fields=["status", "execution_notes", "updated_at"])
        ExecutionEventService.log(order, "ORDER_FAILED", message, payload or {})


class FillProcessingService:

    @staticmethod
    def _is_closing_fill(order: Order) -> bool:
        """
        Détermine si l'ordre est de nature "close" (réduit une position existante
        de side opposé). Convention : un BUY ferme une position SHORT existante,
        un SELL ferme une position LONG existante. S'il n'existe pas de position
        opposée, ce n'est pas un close.

        Le flag `metadata["reduce_only"]=True` force le close même si la
        position correspondante n'est pas trouvée (utile pour les SL/TP brokers).
        """
        if (order.metadata or {}).get("reduce_only") is True:
            return True

        opposite_side = "SHORT" if order.side == "BUY" else "LONG"
        try:
            return order.portfolio.positions.filter(
                symbol=order.symbol,
                side=opposite_side,
                status__in=["OPEN", "PARTIALLY_CLOSED"],
            ).exists()
        except Exception:
            return False

    @staticmethod
    @transaction.atomic
    def register_fill(order: Order, fill_payload: dict):
        """
        Register a single broker fill against an order.

        FIX: idempotent — if a fill with the same ``broker_fill_id`` already
        exists for this order, we return it instead of creating a duplicate.
        Without this, webhook retries / reconcile passes silently doubled the
        accounting and produced fake PnL.
        """
        quantity = _d(fill_payload.get("quantity"))
        price = _d(fill_payload.get("price"))
        notional = _d(fill_payload.get("notional"))
        fee = _d(fill_payload.get("fee"))
        broker_fill_id = fill_payload.get("broker_fill_id")

        if broker_fill_id:
            existing = order.fills.filter(broker_fill_id=str(broker_fill_id)).first()
            if existing:
                return existing

        # Lock the order row to serialize concurrent fill writers.
        Order.objects.select_for_update().filter(pk=order.pk).first()

        fill = ExecutionFill.objects.create(
            order=order,
            broker_fill_id=str(broker_fill_id) if broker_fill_id else None,
            quantity=quantity,
            price=price,
            notional=notional,
            fee=fee,
            fee_currency=fill_payload.get("fee_currency") or order.portfolio.base_currency,
            fill_time=fill_payload.get("fill_time") or timezone.now(),
            liquidity_type=fill_payload.get("liquidity_type"),
            metadata=fill_payload.get("metadata") or {},
        )

        total_qty = sum((_d(x.quantity) for x in order.fills.all()), start=Decimal("0"))
        total_notional = sum((_d(x.notional) for x in order.fills.all()), start=Decimal("0"))
        total_fee = sum((_d(x.fee) for x in order.fills.all()), start=Decimal("0"))

        avg_fill_price = Decimal("0")
        if total_qty > 0:
            weighted_sum = sum((_d(x.quantity) * _d(x.price) for x in order.fills.all()), start=Decimal("0"))
            avg_fill_price = weighted_sum / total_qty

        order.filled_quantity = total_qty
        order.filled_notional = total_notional.quantize(Decimal("0.01"))
        order.actual_fee = total_fee.quantize(Decimal("0.01"))
        order.average_fill_price = avg_fill_price

        if order.filled_quantity >= order.approved_quantity:
            order.status = "FILLED"
            order.filled_at = timezone.now()
        elif order.filled_quantity > 0:
            order.status = "PARTIALLY_FILLED"

        order.save(update_fields=[
            "filled_quantity",
            "filled_notional",
            "actual_fee",
            "average_fill_price",
            "status",
            "filled_at",
            "updated_at",
        ])

        event_type = "ORDER_FILLED" if order.status == "FILLED" else "ORDER_PARTIALLY_FILLED"
        ExecutionEventService.log(order, event_type, "Fill enregistré.", fill_payload)

        # Phase 3 : si ce fill ferme une position existante de side opposé
        # (ex: SELL sur LONG, ou BUY sur SHORT), on délègue à PositionCloseService
        # qui crée un Trade et écrit le realized_pnl.
        # Sinon (ouverture / augmentation), on appelle l'apply normal.
        is_closing_fill = FillProcessingService._is_closing_fill(order)
        if is_closing_fill:
            try:
                from execution.services_close import PositionCloseService
                PositionCloseService.apply_closing_fill_for_order(order=order, fill=fill)
            except Exception as exc:
                # On ne fait pas échouer le fill (déjà persisté). On log + fallback open.
                import logging
                logging.getLogger("leotrade.execution.services").exception(
                    "register_fill.close_failed order_id=%s err=%s — fallback open path",
                    order.id, exc,
                )
                PositionService.apply_fill_to_position(order=order, fill=fill)
        else:
            PositionService.apply_fill_to_position(order=order, fill=fill)

        AccountingBridgeService.apply_fill_accounting(order=order, fill=fill)
        if order.status == "FILLED":
            TradingNotificationService.notify_order_filled(order)

        dashboard_payload = {
            "kind": "fill",
            "order_id": order.id,
            "symbol": order.symbol,
            "status": order.status,
            "filled_quantity": str(order.filled_quantity),
            "average_fill_price": str(order.average_fill_price),
            "filled_notional": str(order.filled_notional),
        }
        portfolio_payload = {
            "kind": "position_or_fill_update",
            "portfolio_id": order.portfolio_id,
            "order_id": order.id,
            "symbol": order.symbol,
            "status": order.status,
        }

        def _broadcast_after_commit():
            RealtimeBroadcastService.broadcast_dashboard_update(
                user_id=order.user_id, payload=dashboard_payload
            )
            RealtimeBroadcastService.broadcast_portfolio_update(
                portfolio_id=order.portfolio_id, payload=portfolio_payload
            )

        transaction.on_commit(_broadcast_after_commit)

        return fill



class PositionService:
    @staticmethod
    @transaction.atomic
    def apply_fill_to_position(order: Order, fill: ExecutionFill):
        portfolio = order.portfolio
        side = "LONG" if order.side == "BUY" else "SHORT"

        if portfolio.broker_account_id and order.broker_account_id != portfolio.broker_account_id:
            raise ValueError("Le broker de l'ordre ne correspond pas au broker du portefeuille.")

        position = portfolio.positions.filter(
            symbol=order.symbol,
            side=side,
            status__in=["OPEN", "PARTIALLY_CLOSED"],
        ).first()

        if position:
            old_qty = _d(position.quantity)
            fill_qty = _d(fill.quantity)
            new_qty = old_qty + fill_qty

            if new_qty <= 0:
                return position

            old_cost = _d(position.average_entry_price) * old_qty
            new_cost = _d(fill.price) * fill_qty
            avg_price = (old_cost + new_cost) / new_qty

            position.quantity = new_qty
            position.average_entry_price = q8(avg_price)
            position.current_price = q8(fill.price)
            position.entry_price = q8(position.entry_price or avg_price)
            position.stop_loss = q8(order.stop_loss)
            position.take_profit = q8(order.take_profit)
            position.notional_value = (_d(fill.price) * new_qty).quantize(Decimal("0.01"))
            position.exposure_value = position.notional_value
            position.margin_used = _d(order.approved_notional).quantize(Decimal("0.01"))
            position.status = "OPEN"
            position.metadata = {**(position.metadata or {}), "last_order_id": order.id}
            position.update_market_metrics()
            position.save()
            return position

        position = Position.objects.create(
            portfolio=portfolio,
            broker_account=portfolio.broker_account,
            asset=order.asset,
            symbol=order.symbol,
            asset_name=order.asset_name or order.symbol,
            side=side,
            quantity=_d(fill.quantity),
            entry_price=q8(fill.price),
            average_entry_price=q8(fill.price),
            current_price=q8(fill.price),
            stop_loss=q8(order.stop_loss),
            take_profit=q8(order.take_profit),
            leverage=_d(order.leverage),
            margin_used=_d(order.approved_notional).quantize(Decimal("0.01")),
            notional_value=_d(fill.notional).quantize(Decimal("0.01")),
            exposure_value=_d(fill.notional).quantize(Decimal("0.01")),
            status="OPEN",
            source="AI_ASSISTED" if order.source == "AI_ASSISTED" else "STRATEGY",
            cost_basis_status="KNOWN",
            broker_order_id=order.broker_order_id,
            opened_at=order.filled_at or timezone.now(),
            metadata={"origin_order_id": order.id},
        )
        position.update_market_metrics()
        position.save()
        return position


class AccountingBridgeService:
    @staticmethod
    @transaction.atomic
    def apply_fill_accounting(order: Order, fill: ExecutionFill):
        portfolio = order.portfolio

        fill_notional = _d(fill.notional).quantize(Decimal("0.01"))
        fill_fee = _d(fill.fee).quantize(Decimal("0.01"))

        # 1. Déverrouiller le cash réservé
        PortfolioAccountingService.release_cash_from_order(
            portfolio=portfolio,
            amount=fill_notional,
            reference_type="ORDER",
            reference_id=str(order.id),
            metadata={"stage": "unlock_before_consume"},
        )

        # 2. Débit réel (TRÈS IMPORTANT)
        PortfolioAccountingService.add_ledger_entry(
            portfolio=portfolio,
            entry_type="TRADE_EXECUTION",
            amount=-fill_notional,
            reference_type="ORDER",
            reference_id=str(order.id),
            metadata={
                "symbol": order.symbol,
                "side": order.side,
                "broker_fill_id": fill.broker_fill_id,
                "stage": "cash_consumption",
            },
        )

        # 3. Frais
        if fill_fee > 0:
            PortfolioAccountingService.apply_fee(
                portfolio=portfolio,
                amount=fill_fee,
                reference_type="ORDER",
                reference_id=str(order.id),
                metadata={"broker_fill_id": fill.broker_fill_id},
            )

        PortfolioService.refresh_portfolio_metrics(portfolio)

class ExecutionOrchestrator:

    @staticmethod
    @transaction.atomic
    def validate_order_risk(order: Order):
        """
        Évalue (ou ré-évalue) l'ordre via RiskGuardService et persiste une
        RiskDecision.

        IDEMPOTENCE — FIX
        -----------------
        Quand l'ordre a été créé par TradeIdeaExecutionService (chemin IA), le
        RiskGuardService a déjà été appelé en amont et un risk_decision_id est
        injecté dans ``order.metadata``. Dans ce cas on NE recourt PAS le risk
        engine ici : ce serait :
          1) un doublon de RiskDecision en base ;
          2) un risque de divergence (qty/notional réajustés deux fois) ;
          3) une perte de performance (re-fetch profil + re-calcul sizing).

        Pour les autres entrées (API REST, Quick Trade, etc.) le contrôle a
        bien lieu — c'est notre garde-fou de dernier recours.
        """
        existing_decision_id = (order.metadata or {}).get("risk_decision_id")
        if existing_decision_id:
            existing = RiskDecisionService.get_by_id(existing_decision_id) if hasattr(
                RiskDecisionService, "get_by_id"
            ) else None
            if existing is None:
                from risk.models import RiskDecision
                existing = RiskDecision.objects.filter(pk=existing_decision_id).first()

            if existing is not None:
                # Si la décision pré-existante était bloquante, on rejette
                # immédiatement sans rappeler le broker.
                if str(getattr(existing, "decision", "")).upper() in {"BLOCK", "REJECT"}:
                    OrderLifecycleService.mark_rejected(
                        order,
                        getattr(existing, "blocking_reason", "")
                        or "Ordre rejeté par le risk engine (décision pré-existante).",
                        {"risk_decision_id": existing.id, "reused": True},
                    )
                    raise ValueError(
                        getattr(existing, "blocking_reason", "")
                        or "Ordre rejeté par le risk engine."
                    )

                # Cas normal : on réutilise la décision sans en créer une nouvelle.
                # Si elle n'est pas encore liée à l'ordre, on la lie maintenant.
                if getattr(existing, "order_id", None) != order.pk:
                    try:
                        existing.order = order
                        existing.save(update_fields=["order", "updated_at"])
                    except Exception:
                        pass
                return existing

        risk_profile = RiskGuardService.get_default_profile(order.portfolio)

        approval = RiskGuardService.validate_trade(
            portfolio=order.portfolio,
            symbol=order.symbol,
            asset=order.asset,
            side=order.side,
            requested_stake=order.requested_stake_amount,
            approved_quantity=order.approved_quantity,
            approved_notional=order.approved_notional,
            entry_price=order.requested_price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            confidence=None,
            signal=order.signal,
            trade_idea=order.trade_idea,
        )

        decision = RiskDecisionService.persist_decision(
            portfolio=order.portfolio,
            risk_profile=risk_profile,
            symbol=order.symbol,
            asset_class=getattr(order.asset, "asset_class", None),
            side=order.side,
            requested_stake=order.requested_stake_amount,
            approved_result=approval,
            requested_quantity=order.requested_quantity,
            requested_notional=order.approved_notional,
            signal=order.signal,
            trade_idea=order.trade_idea,
            order=order,
        )

        if approval.decision in {"BLOCK", "REJECT"}:
            OrderLifecycleService.mark_rejected(
                order,
                approval.blocking_reason or "Ordre rejeté par le risk engine.",
                {"risk_decision_id": decision.id},
            )
            raise ValueError(approval.blocking_reason or "Ordre rejeté par le risk engine.")

        if approval.decision == "REDUCE":
            order.approved_quantity = approval.approved_quantity
            order.approved_notional = approval.approved_notional
            order.requested_stake_amount = approval.approved_stake
            order.save(update_fields=[
                "approved_quantity",
                "approved_notional",
                "requested_stake_amount",
                "updated_at",
            ])

        # Mémorise l'ID de décision pour rendre l'appel idempotent
        # si submit_order était relancé sur le même ordre (retry, reconcile).
        try:
            order.metadata = {
                **(order.metadata or {}),
                "risk_decision_id": decision.id,
            }
            order.save(update_fields=["metadata", "updated_at"])
        except Exception:
            # ne pas faire échouer la phase de risque pour un simple update meta
            pass

        return decision

    @staticmethod
    @transaction.atomic
    def create_order(
            *,
            user,
            portfolio,
            broker_account,
            symbol: str,
            side: str,
            approved_quantity: Decimal,
            requested_stake_amount: Decimal,
            approved_notional: Decimal,
            requested_price: Decimal,
            signal=None,
            trade_idea=None,
            asset=None,
            order_type: str = "MARKET",
            source: str = "AI_ASSISTED",
            stop_loss=None,
            take_profit=None,
            leverage: Decimal = Decimal("1"),
            metadata: dict | None = None,
    ) -> Order:
        order = Order.objects.create(
            user=user,
            portfolio=portfolio,
            broker_account=broker_account,
            signal=signal,
            trade_idea=trade_idea,
            asset=asset,
            symbol=symbol,
            asset_name=getattr(asset, "name", symbol) if asset else symbol,
            side=side,
            order_type=order_type,
            mode=broker_account.mode,
            source=source,
            requested_quantity=approved_quantity,
            approved_quantity=approved_quantity,
            requested_stake_amount=requested_stake_amount,
            approved_notional=approved_notional,
            requested_price=requested_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            leverage=leverage,
            status="PENDING_SUBMIT",
            idempotency_key=f"{broker_account.id}-{portfolio.id}-{uuid4().hex}",
            metadata=metadata or {},
        )

        log_event(
            logger,
            "info",
            "order_created",
            order_id=order.id,
            user_id=user.id,
            portfolio_id=portfolio.id,
            broker_account_id=broker_account.id,
            symbol=symbol,
            side=side,
            approved_quantity=str(approved_quantity),
            approved_notional=str(approved_notional),
            mode=broker_account.mode,
        )

        ExecutionEventService.log(order, "ORDER_CREATED", "Ordre créé localement.")
        TradingNotificationService.notify_order_created(order)

        RealtimeBroadcastService.broadcast_dashboard_update(
            user_id=order.user_id,
            payload={
                "kind": "order_created",
                "order_id": order.id,
                "symbol": order.symbol,
                "side": order.side,
                "status": order.status,
            },
        )
        return order

    @staticmethod
    def submit_order(order: Order):
        """
        Submit a previously-created order to the broker.

        FIXES applied
        -------------
        1. The transaction no longer wraps the broker network call. Holding a
           Postgres transaction open during a possibly slow broker call locks
           rows and risks the dreaded "broker accepted, DB rolled back"
           desync.
        2. Order row is locked + transitioned to ``SUBMITTING`` in a short
           transaction before the broker call. A second concurrent submit
           short-circuits instead of double-firing.
        3. ``mark_submitted`` and ``register_fill`` happen in a separate
           commit *after* the broker confirms — so DB and broker stay
           consistent even on Postgres flake.
        4. On exception, cash lock is released only if it was actually
           applied during this call (idempotent rollback).
        """
        log_event(
            logger,
            "info",
            "order_submit_started",
            order_id=order.id,
            broker=order.broker_account.broker,
            mode=order.mode,
            symbol=order.symbol,
        )

        portfolio = order.portfolio
        cash_locked = False

        # ── Phase 1 (short transaction): risk + cash lock + state transition
        with transaction.atomic():
            locked_order = (
                Order.objects.select_for_update().filter(pk=order.pk).first()
            )
            if locked_order is None:
                raise ValueError(f"Order {order.pk} disappeared.")
            order = locked_order

            if order.status not in ("PENDING_SUBMIT", "FAILED", "REJECTED"):
                # Already in flight — refuse to re-submit.
                raise ValueError(
                    f"Order {order.id} cannot be submitted from status {order.status}."
                )

            ExecutionOrchestrator.validate_order_risk(order)

            PortfolioAccountingService.lock_cash_for_order(
                portfolio=portfolio,
                amount=order.approved_notional,
                reference_type="ORDER",
                reference_id=str(order.id),
                metadata={
                    "symbol": order.symbol,
                    "side": order.side,
                    "mode": order.mode,
                },
            )
            cash_locked = True

            order.status = "SUBMITTING"
            order.save(update_fields=["status", "updated_at"])

            ExecutionEventService.log(
                order, "ORDER_VALIDATED", "Ordre validé avant envoi."
            )

        # ── Phase 2 (no transaction): blocking broker call
        adapter = BrokerAdapterFactory.build(
            broker_account=order.broker_account,
            portfolio=order.portfolio,
        )

        try:
            broker_payload = adapter.submit_order(order)
        except (DatabaseError, TransactionManagementError):
            logger.exception(
                "Transaction/DB error during submit_order order_id=%s symbol=%s",
                order.id,
                order.symbol,
            )
            raise
        except Exception as exc:
            log_event(
                logger,
                "error",
                "order_submit_failed",
                order_id=order.id,
                symbol=order.symbol,
                error=str(exc),
            )
            with transaction.atomic():
                if cash_locked:
                    PortfolioAccountingService.release_cash_from_order(
                        portfolio=portfolio,
                        amount=order.approved_notional,
                        reference_type="ORDER",
                        reference_id=str(order.id),
                        metadata={"rollback": True},
                    )
                OrderLifecycleService.mark_failed(
                    order, str(exc), {"exception": str(exc)}
                )
            raise

        # ── Phase 3 (short transaction): persist broker confirmation + fills
        with transaction.atomic():
            OrderLifecycleService.mark_submitted(order, broker_payload)
            for fill_payload in broker_payload.get("fills", []):
                FillProcessingService.register_fill(order, fill_payload)
            PortfolioService.refresh_portfolio_metrics(order.portfolio)

        return order

    @staticmethod
    @transaction.atomic
    def cancel_order(order: Order):
        if not order.is_open:
            raise ValueError("Cet ordre ne peut plus être annulé.")

        adapter = BrokerAdapterFactory.build(
            broker_account=order.broker_account,
            portfolio=order.portfolio,
        )
        payload = adapter.cancel_order(order)

        remaining_notional = order.approved_notional - order.filled_notional
        if remaining_notional > 0:
            PortfolioAccountingService.release_cash_from_order(
                portfolio=order.portfolio,
                amount=remaining_notional,
                reference_type="ORDER",
                reference_id=str(order.id),
                metadata={"cancel": True},
            )

        OrderLifecycleService.mark_cancelled(order, payload)
        PortfolioService.refresh_portfolio_metrics(order.portfolio)
        return order
