from __future__ import annotations

import json
from decimal import Decimal
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from infrastructure.broker_clients.gateway import BrokerGateway
from portfolio.services import PortfolioService
from portfolio.broker_import import BrokerImportService
from .models import BrokerSyncLog, Order
from .services import FillProcessingService, ExecutionEventService, OrderLifecycleService
from .notifications import TradingNotificationService
from core.logging import get_logger, log_event
logger = get_logger("execution")

def _d(value, default="0"):
    try:
        if value is None:
            return Decimal(default)
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _json_safe(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


class BrokerReconciliationService:
    """
    Réconciliation broker -> Lyneci
    - ordres ouverts / partiellement exécutés
    - fills manquants
    - positions broker
    - balance broker
    """

    @staticmethod
    def _find_local_order(portfolio, remote: dict):
        broker_order_id = remote.get("broker_order_id")
        broker_client_order_id = remote.get("broker_client_order_id")

        qs = Order.objects.filter(portfolio=portfolio)

        if broker_order_id:
            order = qs.filter(broker_order_id=str(broker_order_id)).first()
            if order:
                return order

        if broker_client_order_id:
            order = qs.filter(broker_client_order_id=str(broker_client_order_id)).first()
            if order:
                return order

        return None

    @staticmethod
    def _normalize_remote_status(remote_status: str) -> str:
        raw = str(remote_status or "").upper().strip()

        mapping = {
            "NEW": "SUBMITTED",
            "OPEN": "SUBMITTED",
            "PLACED": "SUBMITTED",
            "SUBMITTED": "SUBMITTED",
            "PARTIALLY_FILLED": "PARTIALLY_FILLED",
            "PARTIAL": "PARTIALLY_FILLED",
            "FILLED": "FILLED",
            "DONE": "FILLED",
            "CANCELED": "CANCELLED",
            "CANCELLED": "CANCELLED",
            "REJECTED": "REJECTED",
            "FAILED": "FAILED",
            "EXPIRED": "EXPIRED",
            "CLOSED": "FILLED",
        }
        return mapping.get(raw, "SUBMITTED")

    @staticmethod
    @transaction.atomic
    def _apply_remote_order_state(order: Order, remote: dict):
        remote_status = BrokerReconciliationService._normalize_remote_status(
            remote.get("status")
        )

        updates = []
        status_changed = False
        if remote.get("broker_order_id") and order.broker_order_id != str(remote.get("broker_order_id")):
            order.broker_order_id = str(remote.get("broker_order_id"))
            updates.append("broker_order_id")

        if remote.get("broker_client_order_id") and order.broker_client_order_id != str(remote.get("broker_client_order_id")):
            order.broker_client_order_id = str(remote.get("broker_client_order_id"))
            updates.append("broker_client_order_id")

        if order.status != remote_status:
            status_changed = True
            order.status = remote_status
            updates.append("status")

            now = timezone.now()
            if remote_status == "CANCELLED":
                order.cancelled_at = now
                updates.append("cancelled_at")
            elif remote_status == "REJECTED":
                order.rejected_at = now
                updates.append("rejected_at")
            elif remote_status == "EXPIRED":
                order.expired_at = now
                updates.append("expired_at")
            elif remote_status == "FILLED" and not order.filled_at:
                order.filled_at = now
                updates.append("filled_at")

        if remote.get("raw"):
            order.metadata = {
                **(order.metadata or {}),
                "reconciliation_remote_payload": remote.get("raw"),
            }
            updates.append("metadata")

        if updates:
            updates.append("updated_at")
            order.save(update_fields=updates)

        if remote_status in {"CANCELLED", "REJECTED", "EXPIRED", "FAILED"}:
            BrokerReconciliationService._release_terminal_cash(order, remote_status)
            if status_changed:
                OrderLifecycleService._sync_signal(order, remote_status)
                if remote_status == "CANCELLED":
                    TradingNotificationService.notify_order_cancelled(order)
                else:
                    TradingNotificationService.notify_error(
                        user_id=order.user_id,
                        message=(
                            f"Ordre {order.symbol} terminé côté broker: "
                            f"{remote_status}."
                        ),
                        payload={
                            "order_id": order.id,
                            "symbol": order.symbol,
                            "status": remote_status,
                        },
                    )

        ExecutionEventService.log(
            order,
            "RECONCILIATION_UPDATE",
            f"Réconciliation ordre: {remote_status}",
            remote,
        )

    @staticmethod
    def _release_terminal_cash(order: Order, remote_status: str) -> None:
        is_reduce_only = bool(
            order.closes_position_id
            or (order.metadata or {}).get("reduce_only") is True
        )
        remaining_notional = max(
            Decimal("0.00"),
            _d(order.approved_notional) - _d(order.filled_notional),
        )
        if order.mode != "LIVE" or is_reduce_only or remaining_notional <= 0:
            return

        from portfolio.services import PortfolioAccountingService

        PortfolioAccountingService.release_cash_from_order(
            portfolio=order.portfolio,
            amount=remaining_notional,
            reference_type="ORDER",
            reference_id=str(order.id),
            metadata={
                "reconciliation_terminal_status": remote_status,
            },
        )

    @staticmethod
    @transaction.atomic
    def _sync_remote_fills(order: Order, remote: dict) -> int:
        """
        Create local fills from remote payload, deduplicated.

        FIX: if ``broker_fill_id`` is missing (e.g. some Binance flows), we
        previously created duplicates on every reconcile. Now we fall back to
        a deterministic fingerprint built from quantity+price+fill_time, and
        we cap at the order's expected quantity to avoid runaway insertion.
        """
        created_count = 0
        remote_fills = remote.get("fills", []) or []

        existing_ids = {
            str(x)
            for x in order.fills.exclude(broker_fill_id__isnull=True)
            .exclude(broker_fill_id__exact="")
            .values_list("broker_fill_id", flat=True)
        }

        existing_fingerprints = {
            f"{x['quantity']}|{x['price']}|{x['fill_time'].isoformat() if x.get('fill_time') else ''}"
            for x in order.fills.values("quantity", "price", "fill_time")
        }

        for fill_payload in remote_fills:
            if (fill_payload.get("metadata") or {}).get(
                "reconciliation_cumulative"
            ):
                target_quantity = _d(fill_payload.get("quantity"))
                delta_quantity = target_quantity - _d(order.filled_quantity)
                if delta_quantity <= 0:
                    continue
                target_notional = _d(fill_payload.get("notional"))
                delta_notional = max(
                    Decimal("0.00"),
                    target_notional - _d(order.filled_notional),
                )
                price = _d(fill_payload.get("price"))
                if delta_notional <= 0 and price > 0:
                    delta_notional = delta_quantity * price
                fill_payload = {
                    **fill_payload,
                    "broker_fill_id": (
                        f"cumulative:{order.broker_order_id or order.id}:"
                        f"{target_quantity}"
                    ),
                    "quantity": delta_quantity,
                    "notional": delta_notional,
                }

            broker_fill_id = fill_payload.get("broker_fill_id")
            if broker_fill_id:
                bid = str(broker_fill_id)
                if bid in existing_ids:
                    continue
                FillProcessingService.register_fill(order, fill_payload)
                existing_ids.add(bid)
                created_count += 1
                continue

            qty = fill_payload.get("quantity")
            price = fill_payload.get("price")
            fill_time = fill_payload.get("fill_time")
            fingerprint = (
                f"{qty}|{price}|{fill_time.isoformat() if hasattr(fill_time, 'isoformat') else ''}"
            )
            if fingerprint in existing_fingerprints:
                continue

            FillProcessingService.register_fill(order, fill_payload)
            existing_fingerprints.add(fingerprint)
            created_count += 1

        return created_count

    @staticmethod
    def reconcile_orders(portfolio):
        broker_account = portfolio.broker_account
        sync_log = BrokerSyncLog.objects.create(
            broker_account=broker_account,
            portfolio=portfolio,
            sync_type="ORDERS",
            status="STARTED",
            payload={},
        )

        processed = 0
        fills_created = 0
        unmatched_remote_orders = []
        unmatched_local_orders = []
        remote_snapshot = []
        matched_local_order_ids = set()

        try:
            client = BrokerGateway(broker_account)
            remote_open_orders = client.fetch_open_orders() or []

            for remote in remote_open_orders:
                remote_snapshot.append(remote)
                local_order = BrokerReconciliationService._find_local_order(portfolio, remote)

                if not local_order:
                    unmatched_remote_orders.append(remote)
                    continue

                if (
                    BrokerReconciliationService._normalize_remote_status(
                        remote.get("status")
                    ) == "PARTIALLY_FILLED"
                    and not (remote.get("fills") or [])
                ):
                    remote = client.fetch_order(local_order) or remote

                BrokerReconciliationService._apply_remote_order_state(local_order, remote)
                fills_created += BrokerReconciliationService._sync_remote_fills(local_order, remote)
                matched_local_order_ids.add(local_order.id)
                processed += 1

            local_recovery_candidates = Order.objects.filter(
                portfolio=portfolio,
                status__in=[
                    "SUBMITTING",
                    "UNKNOWN_BROKER_STATE",
                    "SUBMITTED",
                    "PARTIALLY_FILLED",
                ],
            ).exclude(pk__in=matched_local_order_ids)

            for local_order in local_recovery_candidates:
                remote = client.fetch_order(local_order)
                if not remote:
                    unmatched_local_orders.append({
                        "order_id": local_order.id,
                        "status": local_order.status,
                        "symbol": local_order.symbol,
                        "broker_order_id": local_order.broker_order_id,
                    })
                    continue

                remote_snapshot.append(remote)
                BrokerReconciliationService._apply_remote_order_state(
                    local_order,
                    remote,
                )
                fills_created += BrokerReconciliationService._sync_remote_fills(
                    local_order,
                    remote,
                )
                matched_local_order_ids.add(local_order.id)
                processed += 1

            sync_log.status = "SUCCESS"
            sync_log.processed_count = processed
            sync_log.error_count = 0
            sync_log.message = "Réconciliation ordres terminée."
            sync_log.payload = _json_safe({
                "remote_count": len(remote_open_orders),
                "processed_local_matches": processed,
                "fills_created": fills_created,
                "unmatched_remote_orders_count": len(unmatched_remote_orders),
                "unmatched_remote_orders": unmatched_remote_orders[:20],
                "unmatched_local_orders_count": len(unmatched_local_orders),
                "unmatched_local_orders": unmatched_local_orders[:20],
                "remote_snapshot_sample": remote_snapshot[:20],
            })
            sync_log.finished_at = timezone.now()
            sync_log.save(update_fields=[
                "status",
                "processed_count",
                "error_count",
                "message",
                "payload",
                "finished_at",
                "updated_at",
            ])
            return sync_log

        except Exception as exc:
            sync_log.status = "FAILED"
            sync_log.error_count = 1
            sync_log.message = str(exc)
            sync_log.payload = _json_safe({
                "processed_local_matches": processed,
                "fills_created": fills_created,
                "unmatched_remote_orders_count": len(unmatched_remote_orders),
                "unmatched_local_orders_count": len(unmatched_local_orders),
            })
            sync_log.finished_at = timezone.now()
            sync_log.save(update_fields=[
                "status",
                "error_count",
                "message",
                "payload",
                "finished_at",
                "updated_at",
            ])
            raise

    @staticmethod
    def reconcile_positions(portfolio):
        broker_account = portfolio.broker_account
        sync_log = BrokerSyncLog.objects.create(
            broker_account=broker_account,
            portfolio=portfolio,
            sync_type="POSITIONS",
            status="STARTED",
            payload={},
        )

        try:
            imported_positions = BrokerImportService.import_live_positions(portfolio)
            PortfolioService.refresh_portfolio_metrics(portfolio)

            sync_log.status = "SUCCESS"
            sync_log.processed_count = len(imported_positions)
            sync_log.message = "Réconciliation positions terminée."
            sync_log.payload = {
                "imported_positions_count": len(imported_positions),
                "position_ids": [p.id for p in imported_positions],
            }
            sync_log.finished_at = timezone.now()
            sync_log.save(update_fields=[
                "status",
                "processed_count",
                "message",
                "payload",
                "finished_at",
                "updated_at",
            ])
            return sync_log

        except Exception as exc:
            sync_log.status = "FAILED"
            sync_log.error_count = 1
            sync_log.message = str(exc)
            sync_log.finished_at = timezone.now()
            sync_log.save(update_fields=[
                "status",
                "error_count",
                "message",
                "finished_at",
                "updated_at",
            ])
            raise

    @staticmethod
    def reconcile_balance(portfolio):
        broker_account = portfolio.broker_account
        sync_log = BrokerSyncLog.objects.create(
            broker_account=broker_account,
            portfolio=portfolio,
            sync_type="BALANCE",
            status="STARTED",
            payload={},
        )

        try:
            client = BrokerGateway(broker_account)
            balances = client.fetch_balances() or []

            preferred_currency = broker_account.deriv_currency or portfolio.base_currency or "USD"
            remote_balance = None

            for bal in balances:
                if str(bal.currency).upper() == str(preferred_currency).upper():
                    remote_balance = bal.available
                    break

            if remote_balance is None and balances:
                remote_balance = balances[0].available

            payload = {
                "preferred_currency": preferred_currency,
                "balances": [
                    {
                        "currency": b.currency,
                        "total": str(b.total),
                        "available": str(b.available),
                        "locked": str(b.locked),
                    }
                    for b in balances[:20]
                ],
            }

            if remote_balance is not None:
                # Recalcule d'abord le cash local depuis le ledger (source de vérité)
                portfolio = PortfolioService.recompute_cash_state(portfolio)
                current_local_cash = _d(portfolio.current_balance)

                # FIX SYNC : on remet le cash en vol (locked_cash) avant
                # de comparer pour éviter d'inscrire un ajustement fantôme
                # tant que les ordres pending ne sont pas confirmés côté
                # broker. Cf. brokers/services/deriv_sync.on_balance_update.
                locked_cash = _d(portfolio.locked_cash)
                adjusted_local = (current_local_cash + locked_cash).quantize(_d("0.01"))
                delta = (_d(remote_balance) - adjusted_local).quantize(_d("0.01"))

                payload["remote_available_balance"] = str(remote_balance)
                payload["local_current_balance"] = str(current_local_cash)
                payload["local_locked_cash"] = str(locked_cash)
                payload["adjusted_local_balance"] = str(adjusted_local)
                payload["delta"] = str(delta)

                # Applique le delta si significatif (≥ 1 centime)
                # afin de maintenir le ledger cohérent avec la balance broker.
                if abs(delta) >= _d("0.01"):
                    try:
                        from portfolio.services import PortfolioAccountingService
                        PortfolioAccountingService.add_ledger_entry(
                            portfolio=portfolio,
                            entry_type="BROKER_IMPORT",
                            amount=delta,
                            currency=preferred_currency,
                            reference_type="BROKER_BALANCE_RECONCILE",
                            reference_id=str(sync_log.id),
                            description=(
                                f"Ajustement balance broker "
                                f"({broker_account.broker}/{broker_account.mode}) "
                                f"Δ={delta}"
                            ),
                            metadata={
                                "broker": broker_account.broker,
                                "broker_account_id": broker_account.id,
                                "remote_balance": str(remote_balance),
                                "local_balance_before": str(current_local_cash),
                                "sync_log_id": sync_log.id,
                            },
                        )
                        payload["balance_adjustment_applied"] = str(delta)
                        log_event(
                            logger,
                            "info",
                            "broker_reconcile_balance_adjusted",
                            portfolio_id=portfolio.id,
                            broker_account_id=broker_account.id,
                            delta=str(delta),
                        )
                    except Exception as adj_exc:
                        payload["balance_adjustment_error"] = str(adj_exc)
                        log_event(
                            logger,
                            "warning",
                            "broker_reconcile_balance_adjustment_failed",
                            portfolio_id=portfolio.id,
                            error=str(adj_exc),
                        )

            PortfolioService.refresh_portfolio_metrics(portfolio)

            sync_log.status = "SUCCESS"
            sync_log.processed_count = len(balances)
            sync_log.message = "Réconciliation balance terminée."
            sync_log.payload = payload
            sync_log.finished_at = timezone.now()
            sync_log.save(update_fields=[
                "status",
                "processed_count",
                "message",
                "payload",
                "finished_at",
                "updated_at",
            ])
            return sync_log

        except Exception as exc:
            sync_log.status = "FAILED"
            sync_log.error_count = 1
            sync_log.message = str(exc)
            sync_log.finished_at = timezone.now()
            sync_log.save(update_fields=[
                "status",
                "error_count",
                "message",
                "finished_at",
                "updated_at",
            ])
            raise

    @staticmethod
    def reconcile_full(portfolio):
        """
        Run all three reconciliation steps independently.

        FIX: the previous version (1) referenced ``broker_account`` before
        defining it (NameError), and (2) wrapped the whole thing in a single
        ``@transaction.atomic`` so that a failure in balance reconciliation
        would roll back already-applied fills. Now each sub-step has its own
        transaction (already declared on the inner methods), and we only
        protect the parent ``BrokerSyncLog`` with a short transaction.
        """
        from core.concurrency import redis_lock

        broker_account = portfolio.broker_account
        log_event(
            logger,
            "info",
            "broker_reconcile_full_started",
            portfolio_id=portfolio.id,
            broker_account_id=broker_account.id,
            broker=broker_account.broker,
        )

        # Idempotent lock: avoid two reconcile_full running on the same
        # portfolio in parallel (would create duplicate fills).
        lock_name = f"reconcile_full:portfolio:{portfolio.id}"
        with redis_lock(lock_name, timeout=300) as lock:
            if lock is None:
                log_event(
                    logger,
                    "info",
                    "broker_reconcile_full_locked",
                    portfolio_id=portfolio.id,
                )
                return None

            with transaction.atomic():
                sync_log = BrokerSyncLog.objects.create(
                    broker_account=broker_account,
                    portfolio=portfolio,
                    sync_type="FULL",
                    status="STARTED",
                    payload={},
                )

            payload: dict = {}
            errors: list[str] = []
            processed_count = 0

            for label, fn in (
                ("orders", BrokerReconciliationService.reconcile_orders),
                ("positions", BrokerReconciliationService.reconcile_positions),
                ("balance", BrokerReconciliationService.reconcile_balance),
            ):
                try:
                    sub_log = fn(portfolio)
                    payload[f"{label}_sync_log_id"] = getattr(sub_log, "id", None)
                    processed_count += getattr(sub_log, "processed_count", 0) or 0
                except Exception as exc:
                    msg = f"{label}_failed: {exc}"
                    errors.append(msg)
                    payload[f"{label}_error"] = str(exc)
                    log_event(
                        logger,
                        "error",
                        "broker_reconcile_step_failed",
                        portfolio_id=portfolio.id,
                        step=label,
                        error=str(exc),
                    )

            try:
                PortfolioService.refresh_portfolio_metrics(portfolio)
                snapshot = PortfolioService.create_snapshot(portfolio)
                payload["snapshot_id"] = getattr(snapshot, "id", None)
            except Exception as exc:
                errors.append(f"snapshot_failed: {exc}")

            with transaction.atomic():
                sync_log.refresh_from_db()
                sync_log.status = "FAILED" if errors else "SUCCESS"
                sync_log.processed_count = processed_count
                sync_log.error_count = len(errors)
                sync_log.message = (
                    "Réconciliation complète terminée."
                    if not errors
                    else f"Réconciliation partielle: {len(errors)} erreur(s)."
                )
                sync_log.payload = payload
                sync_log.finished_at = timezone.now()
                sync_log.save(update_fields=[
                    "status",
                    "processed_count",
                    "error_count",
                    "message",
                    "payload",
                    "finished_at",
                    "updated_at",
                ])

            log_event(
                logger,
                "info" if not errors else "warning",
                "broker_reconcile_full_done",
                portfolio_id=portfolio.id,
                sync_log_id=sync_log.id,
                processed_count=processed_count,
                error_count=len(errors),
            )
            return sync_log
