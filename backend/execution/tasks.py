from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from celery import shared_task
from django.conf import settings
from django.db import transaction as db_tx
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.retry import is_retryable_exception
from portfolio.models import Portfolio
from risk.services import RiskStateService, RiskGuardService
from .reconciliation import BrokerReconciliationService

log = logging.getLogger("leotrade.execution.tasks")


@shared_task
def reconcile_portfolio_orders_task(portfolio_id: int):
    portfolio = Portfolio.objects.filter(pk=portfolio_id, is_active=True).first()
    if not portfolio:
        return {"status": "missing"}
    if portfolio.broker_account.mode != "LIVE":
        return {"status": "skipped", "reason": "paper_portfolio"}

    log = BrokerReconciliationService.reconcile_orders(portfolio)
    return {
        "status": log.status,
        "processed_count": log.processed_count,
        "error_count": log.error_count,
    }


@shared_task
def reconcile_all_active_portfolios_task():
    payload = []
    for portfolio in Portfolio.objects.filter(
        is_active=True,
        broker_account__is_active=True,
        broker_account__mode="LIVE",
    ):
        try:
            log = BrokerReconciliationService.reconcile_orders(portfolio)
            payload.append({
                "portfolio_id": portfolio.id,
                "status": log.status,
                "processed_count": log.processed_count,
            })
        except Exception as exc:
            payload.append({
                "portfolio_id": portfolio.id,
                "status": "FAILED",
                "error": str(exc),
            })
            from notifications.shortcuts import notify
            notify(
                portfolio.user, "BROKER_RECONCILIATION_FAILED",
                title=f"Réconciliation broker échouée — {portfolio.name}",
                message=(
                    f"La réconciliation des ordres de « {portfolio.name} » a échoué : "
                    f"{str(exc)[:200]}. Les soldes affichés peuvent être temporairement décalés."
                ),
                payload={"portfolio_id": portfolio.id, "error": str(exc)[:500]},
                dedupe_key=f"reconcile_failed:{portfolio.id}",
            )
    return payload


@shared_task(
    name="execution.tasks.recover_stale_execution_orders_task",
    acks_late=True,
)
def recover_stale_execution_orders_task():
    """Répare les ordres abandonnés sans jamais rejouer une mutation LIVE."""
    from core.models import OutboxEvent
    from core.outbox import OutboxService
    from execution.event_topics import (
        ORDER_SUBMIT_REQUESTED,
        PORTFOLIO_RECONCILE_REQUESTED,
    )
    from execution.models import Order
    from execution.services import OrderLifecycleService

    stale_seconds = int(
        getattr(settings, "EXECUTION_SUBMIT_STALE_SECONDS", 180)
    )
    alert_seconds = int(
        getattr(settings, "EXECUTION_UNKNOWN_ALERT_SECONDS", 300)
    )
    batch_size = int(
        getattr(settings, "EXECUTION_RECOVERY_BATCH_SIZE", 100)
    )
    now = timezone.now()
    stale_before = now - timedelta(seconds=stale_seconds)
    candidate_ids = list(
        Order.objects.filter(
            status__in=[
                "PENDING_SUBMIT",
                "SUBMITTING",
                "UNKNOWN_BROKER_STATE",
            ],
            updated_at__lt=stale_before,
        )
        .order_by("updated_at")
        .values_list("id", flat=True)[:batch_size]
    )

    stats = {
        "scanned": len(candidate_ids),
        "requeued": 0,
        "marked_unknown": 0,
        "reconcile_requested": 0,
        "frozen_portfolios": 0,
        "manual_review": 0,
    }
    portfolios_to_freeze = {}

    for order_id in candidate_ids:
        with db_tx.atomic():
            order = (
                Order.objects.select_for_update()
                .select_related("portfolio", "portfolio__user", "broker_account")
                .get(pk=order_id)
            )
            if order.updated_at >= stale_before:
                continue

            previous_updated_at = order.updated_at
            metadata = dict(order.metadata or {})
            recovery_attempt = int(metadata.get("recovery_attempt", 0)) + 1
            metadata.update({
                "recovery_attempt": recovery_attempt,
                "last_recovery_at": now.isoformat(),
            })

            if order.status == "PENDING_SUBMIT":
                was_queued = OutboxEvent.objects.filter(
                    topic=ORDER_SUBMIT_REQUESTED,
                    aggregate_type="execution.Order",
                    aggregate_id=str(order.id),
                ).exists()
                if not was_queued:
                    metadata["manual_review_reason"] = "pending_without_submit_event"
                    order.metadata = metadata
                    order.save(update_fields=["metadata", "updated_at"])
                    stats["manual_review"] += 1
                    continue

                order.metadata = metadata
                order.save(update_fields=["metadata", "updated_at"])
                OutboxService.enqueue(
                    topic=ORDER_SUBMIT_REQUESTED,
                    aggregate_type="execution.Order",
                    aggregate_id=order.id,
                    payload={"order_id": order.id, "recovery": True},
                    idempotency_key=(
                        f"order:{order.id}:recovery-submit:{recovery_attempt}"
                    ),
                )
                stats["requeued"] += 1
                continue

            if order.mode == "PAPER":
                order.status = "PENDING_SUBMIT"
                order.metadata = {
                    **metadata,
                    "paper_replay_after_worker_loss": True,
                }
                order.save(update_fields=["status", "metadata", "updated_at"])
                OutboxService.enqueue(
                    topic=ORDER_SUBMIT_REQUESTED,
                    aggregate_type="execution.Order",
                    aggregate_id=order.id,
                    payload={"order_id": order.id, "recovery": True},
                    idempotency_key=(
                        f"order:{order.id}:paper-recovery:{recovery_attempt}"
                    ),
                )
                stats["requeued"] += 1
                continue

            if order.status == "SUBMITTING":
                order.metadata = metadata
                order.save(update_fields=["metadata", "updated_at"])
                OrderLifecycleService.mark_unknown(
                    order,
                    "Worker interrompu pendant la soumission; état broker à réconcilier.",
                    {"recovery_attempt": recovery_attempt, "worker_lost": True},
                )
                stats["marked_unknown"] += 1
                continue

            order.metadata = metadata
            order.save(update_fields=["metadata", "updated_at"])
            OutboxService.enqueue(
                topic=PORTFOLIO_RECONCILE_REQUESTED,
                aggregate_type="portfolio.Portfolio",
                aggregate_id=order.portfolio_id,
                payload={
                    "portfolio_id": order.portfolio_id,
                    "order_id": order.id,
                    "recovery": True,
                },
                idempotency_key=(
                    f"order:{order.id}:recovery-reconcile:{recovery_attempt}"
                ),
            )
            stats["reconcile_requested"] += 1

            unknown_at = parse_datetime(
                str(metadata.get("broker_state_unknown_at") or "")
            )
            if unknown_at is None:
                unknown_at = previous_updated_at
            if now - unknown_at >= timedelta(seconds=alert_seconds):
                portfolios_to_freeze[order.portfolio_id] = (order.portfolio, order)

    for portfolio, order in portfolios_to_freeze.values():
        from notifications.shortcuts import notify

        notify(
            portfolio.user,
            "BROKER_ERROR",
            title=f"Ordre broker non résolu — {portfolio.name}",
            message=(
                f"L'ordre #{order.id} ({order.symbol}) reste dans un état broker "
                "inconnu. Les nouvelles entrées sont bloquées jusqu'à vérification."
            ),
            payload={
                "portfolio_id": portfolio.id,
                "order_id": order.id,
                "broker_account_id": order.broker_account_id,
            },
            dedupe_key=f"unknown_broker_order:{order.id}",
        )
        if not RiskGuardService.has_active_kill_switch(portfolio):
            profile = RiskGuardService.get_default_profile(portfolio)
            RiskGuardService.trigger_kill_switch(
                portfolio,
                profile,
                "BROKER_STATE_UNKNOWN",
                f"Ordre #{order.id} non résolu après {alert_seconds} secondes.",
                payload={"order_id": order.id},
            )
            stats["frozen_portfolios"] += 1

    return stats


@shared_task
def refresh_daily_risk_states_task():
    payload = []
    for portfolio in Portfolio.objects.filter(is_active=True):
        state = RiskStateService.refresh_daily_state(portfolio)
        payload.append({
            "portfolio_id": portfolio.id,
            "day": str(state.day),
            "loss_percent": str(state.total_loss_percent),
            "blocked": state.blocked_new_positions,
        })
    return payload


@shared_task
def refresh_weekly_risk_states_task():
    payload = []
    for portfolio in Portfolio.objects.filter(is_active=True):
        state = RiskStateService.refresh_weekly_state(portfolio)
        payload.append({
            "portfolio_id": portfolio.id,
            "week_start": str(state.week_start),
            "loss_percent": str(state.total_loss_percent),
            "blocked": state.blocked_new_positions,
        })
    return payload


@shared_task
def auto_enforce_kill_switch_task():
    payload = []
    for portfolio in Portfolio.objects.filter(is_active=True):
        profile = RiskGuardService.get_default_profile(portfolio)
        daily = RiskStateService.refresh_daily_state(portfolio)
        weekly = RiskStateService.refresh_weekly_state(portfolio)

        triggered = False

        if daily.total_loss_percent >= profile.max_daily_loss and profile.kill_switch_enabled:
            RiskGuardService.trigger_kill_switch(
                portfolio,
                profile,
                "DAILY_LOSS_LIMIT",
                "Kill switch automatique: perte journalière maximale atteinte.",
                payload={"daily_loss_percent": str(daily.total_loss_percent)},
            )
            triggered = True

        elif weekly.total_loss_percent >= profile.max_weekly_loss and profile.kill_switch_enabled:
            RiskGuardService.trigger_kill_switch(
                portfolio,
                profile,
                "WEEKLY_LOSS_LIMIT",
                "Kill switch automatique: perte hebdomadaire maximale atteinte.",
                payload={"weekly_loss_percent": str(weekly.total_loss_percent)},
            )
            triggered = True

        elif portfolio.current_drawdown_percent >= float(profile.max_drawdown) and profile.kill_switch_enabled:
            RiskGuardService.trigger_kill_switch(
                portfolio,
                profile,
                "MAX_DRAWDOWN",
                "Kill switch automatique: drawdown maximal atteint.",
                payload={"drawdown_percent": str(portfolio.current_drawdown_percent)},
            )
            triggered = True

        payload.append({
            "portfolio_id": portfolio.id,
            "triggered": triggered,
        })

    return payload


# =============================================================================
# Phase 4 — Soumission broker post-orchestrator
# =============================================================================

@shared_task(
    name="execution.tasks.submit_order_to_broker_task",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def submit_order_to_broker_task(self, order_id: int):
    """
    Soumission effective d'un Order PENDING_SUBMIT au broker.

    Appelée par l'Outbox transactionnel après commit.

    Garanties :
    - Revendication atomique PENDING_SUBMIT -> SUBMITTING
    - Une livraison Outbox dupliquée devient un noop
    - En cas d'échec broker : libère le cash lock + passe en FAILED
    - En cas de succès : enregistre les fills via FillProcessingService
    """
    from execution.adapters.factory import BrokerAdapterFactory
    from execution.models import Order
    from execution.services import (
        ExecutionOrchestrator,
        FillProcessingService,
        OrderLifecycleService,
    )
    from core.feature_flags import is_trading_enabled
    from portfolio.models import Position
    from portfolio.services import PortfolioService

    with db_tx.atomic():
        order = (
            Order.objects
            .select_for_update()
            .select_related(
                "portfolio",
                "broker_account",
                "user",
                "closes_position",
                "signal",
                "signal__strategy",
                "strategy_deployment",
            )
            .filter(pk=order_id)
            .first()
        )
        if not order:
            log.warning("submit_order_to_broker_task.order_not_found order_id=%s", order_id)
            return {"ok": False, "err": "order_not_found"}

        if order.status != "PENDING_SUBMIT":
            log.info(
                "submit_order_to_broker_task.skipped order_id=%s status=%s",
                order_id, order.status,
            )
            return {"ok": True, "skipped": True, "status": order.status}

        if not is_trading_enabled():
            _mark_rejected_and_release(
                order,
                "Trading globalement désactivé (kill switch)",
            )
            return {"ok": False, "err": "trading_disabled"}

        is_reduce_only_hint = bool(
            order.closes_position_id
            or (order.metadata or {}).get("reduce_only") is True
        )
        if (
            not is_reduce_only_hint
            and RiskGuardService.has_active_kill_switch(order.portfolio)
        ):
            _mark_rejected_and_release(
                order,
                "Kill switch actif sur le portefeuille.",
            )
            return {"ok": False, "err": "portfolio_kill_switch"}

        try:
            ExecutionOrchestrator.validate_strategy_deployment(order)
        except Exception as exc:
            _mark_failed_and_release(order, f"strategy_deployment_invalid: {exc}")
            return {"ok": False, "err": str(exc)}

        order.status = "SUBMITTING"
        order.save(update_fields=["status", "updated_at"])
        from execution.services import ExecutionEventService

        ExecutionEventService.log(
            order,
            "ORDER_VALIDATED",
            "Ordre revendiqué par le worker d'exécution.",
        )

    log.info(
        "submit_order_to_broker_task.start order_id=%s mode=%s symbol=%s side=%s",
        order_id, order.mode, order.symbol, order.side,
    )

    # 1. Construit l'adapter approprié (PaperBrokerAdapter en mode PAPER)
    try:
        adapter = BrokerAdapterFactory.build(order.broker_account, order.portfolio)
    except Exception as exc:
        log.exception(
            "submit_order_to_broker_task.adapter_build_failed order_id=%s err=%s",
            order_id, exc,
        )
        _mark_failed_and_release(order, f"adapter_build_failed: {exc}")
        return {"ok": False, "err": str(exc)}

    close_position = None
    if order.closes_position_id or (order.metadata or {}).get("reduce_only") is True:
        target_position_id = (
            order.closes_position_id
            or (order.metadata or {}).get("closes_position_id")
        )
        close_position = Position.objects.filter(
            pk=target_position_id,
            portfolio=order.portfolio,
            broker_account=order.broker_account,
            status__in=["OPEN", "PARTIALLY_CLOSED"],
        ).first()
        expected_side = (
            "SELL"
            if close_position is not None and close_position.side == "LONG"
            else "BUY"
        )
        if (
            close_position is None
            or order.side != expected_side
            or order.approved_quantity > close_position.quantity
        ):
            _mark_failed_and_release(
                order,
                "unsafe_reduce_only_order: target position mismatch",
            )
            return {"ok": False, "err": "unsafe_reduce_only_order"}

    # 2. Appel broker — HORS transaction DB (peut être lent / réseau / WS)
    try:
        broker_payload = (
            adapter.close_position(close_position, order)
            if close_position is not None
            else adapter.submit_order(order)
        )
    except Exception as exc:
        log.exception(
            "submit_order_to_broker_task.broker_call_failed order_id=%s err=%s",
            order_id, exc,
        )
        if is_retryable_exception(exc):
            _mark_unknown(order, exc)
            return {
                "ok": False,
                "unknown_broker_state": True,
                "err": type(exc).__name__,
            }
        _mark_failed_and_release(order, f"broker_error: {exc}")
        return {"ok": False, "err": str(exc)}

    # 3. Persistance atomique du retour broker
    try:
        with db_tx.atomic():
            OrderLifecycleService.mark_submitted(order, broker_payload or {})

            for fill_payload in (broker_payload or {}).get("fills") or []:
                FillProcessingService.register_fill(order, fill_payload)

            PortfolioService.refresh_portfolio_metrics(order.portfolio)
    except Exception as exc:
        log.exception(
            "submit_order_to_broker_task.persist_failed order_id=%s err=%s",
            order_id, exc,
        )
        _mark_unknown(
            order,
            RuntimeError(f"broker_confirmed_but_persistence_failed: {type(exc).__name__}"),
            payload={
                "broker_payload": broker_payload or {},
                "persistence_error": type(exc).__name__,
            },
        )
        return {
            "ok": False,
            "unknown_broker_state": True,
            "err": f"persist_failed: {type(exc).__name__}",
        }

    order.refresh_from_db()
    log.info(
        "submit_order_to_broker_task.ok order_id=%s broker_order_id=%s status=%s",
        order_id,
        getattr(order, "broker_order_id", None),
        order.status,
    )
    return {
        "ok": True,
        "order_id": order_id,
        "broker_order_id": getattr(order, "broker_order_id", None),
        "status": order.status,
    }


def _mark_rejected_and_release(order, reason: str):
    from execution.services import OrderLifecycleService
    from portfolio.services import PortfolioAccountingService

    is_reduce_only = bool(
        order.closes_position_id
        or (order.metadata or {}).get("reduce_only") is True
    )
    if order.mode == "LIVE" and not is_reduce_only:
        try:
            PortfolioAccountingService.release_cash_from_order(
                portfolio=order.portfolio,
                amount=order.approved_notional,
                reference_type="ORDER",
                reference_id=str(order.id),
                metadata={"kill_switch": True},
            )
        except Exception:
            log.exception(
                "submit_order_to_broker_task.kill_switch_release_failed order_id=%s",
                order.id,
            )
    OrderLifecycleService.mark_rejected(order, reason, {"kill_switch": True})


def _mark_failed_and_release(order, reason: str):
    """
    Met l'ordre en FAILED et libère le cash lock (LIVE only).
    """
    from execution.services import OrderLifecycleService
    from portfolio.services import PortfolioAccountingService

    with db_tx.atomic():
        is_reduce_only = bool(
            order.closes_position_id
            or (order.metadata or {}).get("reduce_only") is True
        )
        if order.mode == "LIVE" and not is_reduce_only:
            try:
                PortfolioAccountingService.release_cash_from_order(
                    portfolio=order.portfolio,
                    amount=order.approved_notional,
                    reference_type="ORDER",
                    reference_id=str(order.id),
                )
            except Exception:
                log.exception(
                    "submit_order_to_broker_task.cash_release_failed order_id=%s",
                    order.id,
                )
        OrderLifecycleService.mark_failed(order, reason)
        if is_reduce_only:
            from execution.protection import PositionProtectionService
            PositionProtectionService.mark_execution_failed(order, reason)


def _mark_unknown(order, exc: Exception, payload: dict | None = None):
    from execution.services import OrderLifecycleService

    with db_tx.atomic():
        OrderLifecycleService.mark_unknown(
            order,
            "Réponse broker perdue ou ambiguë; réconciliation requise.",
            payload or {"exception_type": type(exc).__name__},
        )
        if order.closes_position_id or (order.metadata or {}).get("reduce_only") is True:
            from execution.protection import PositionProtectionService
            PositionProtectionService.mark_execution_unknown(order, str(exc))


@shared_task(name="execution.tasks.evaluate_position_protections_task", bind=True)
def evaluate_position_protections_task(self):
    from core.redis_lock import single_run
    from execution.protection import PositionProtectionService

    with single_run("lock:evaluate_position_protections", ttl=4) as acquired:
        if not acquired:
            return {"skipped": True}
        return PositionProtectionService.evaluate_active()

# Enregistre les tâches de maintenance du module annexe dans le worker.
from execution import tasks_maintenance  # noqa: E402,F401
