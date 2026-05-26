import logging
from decimal import Decimal

from celery import shared_task
from django.db import transaction as db_tx
from django.utils import timezone

from portfolio.models import Portfolio
from risk.services import RiskStateService, RiskGuardService
from .reconciliation import BrokerReconciliationService

log = logging.getLogger("leotrade.execution.tasks")


@shared_task
def reconcile_portfolio_orders_task(portfolio_id: int):
    portfolio = Portfolio.objects.filter(pk=portfolio_id, is_active=True).first()
    if not portfolio:
        return {"status": "missing"}

    log = BrokerReconciliationService.reconcile_orders(portfolio)
    return {
        "status": log.status,
        "processed_count": log.processed_count,
        "error_count": log.error_count,
    }


@shared_task
def reconcile_all_active_portfolios_task():
    payload = []
    for portfolio in Portfolio.objects.filter(is_active=True, broker_account__is_active=True):
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
    return payload


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

@shared_task(name="execution.tasks.submit_order_to_broker_task", bind=True)
def submit_order_to_broker_task(self, order_id: int):
    """
    Soumission effective d'un Order PENDING_SUBMIT au broker.

    Appelée par ExecutionOrchestrator.submit() via transaction.on_commit
    (cf. execution/orchestrator.py).

    Garanties :
    - L'ordre doit être en PENDING_SUBMIT (sinon noop, idempotent)
    - En cas d'échec broker : libère le cash lock + passe en FAILED
    - En cas de succès : enregistre les fills via FillProcessingService
    """
    from execution.adapters.factory import BrokerAdapterFactory
    from execution.models import Order
    from execution.services import FillProcessingService, OrderLifecycleService
    from portfolio.services import PortfolioAccountingService, PortfolioService

    order = (
        Order.objects
        .select_related("portfolio", "broker_account", "user")
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

    # 2. Appel broker — HORS transaction DB (peut être lent / réseau / WS)
    try:
        broker_payload = adapter.submit_order(order)
    except Exception as exc:
        log.exception(
            "submit_order_to_broker_task.broker_call_failed order_id=%s err=%s",
            order_id, exc,
        )
        _mark_failed_and_release(order, f"broker_error: {exc}")
        return {"ok": False, "err": str(exc)}

    # 3. Persistance atomique du retour broker
    try:
        with db_tx.atomic():
            # Mark submitted (broker_order_id, broker_client_order_id, status)
            try:
                OrderLifecycleService.mark_submitted(order, broker_payload or {})
            except Exception:
                # Pas tous les adapters n'implémentent ça : best-effort
                _set_order_field(order, "broker_order_id", (broker_payload or {}).get("broker_order_id"))
                _set_order_field(order, "broker_client_order_id", (broker_payload or {}).get("broker_client_order_id"))
                if not order.submitted_at:
                    order.submitted_at = timezone.now()
                if order.status == "PENDING_SUBMIT":
                    order.status = "SUBMITTED"
                order.save(update_fields=[
                    "broker_order_id", "broker_client_order_id",
                    "submitted_at", "status", "updated_at",
                ])

            # Enregistrement des fills retournés par le broker (le cas échéant)
            for fill_payload in (broker_payload or {}).get("fills") or []:
                try:
                    FillProcessingService.register_fill(order, fill_payload)
                except Exception as exc:
                    log.warning(
                        "submit_order_to_broker_task.fill_register_failed order_id=%s err=%s",
                        order_id, exc,
                    )

            # Refresh portfolio metrics
            PortfolioService.refresh_portfolio_metrics(order.portfolio)
    except Exception as exc:
        log.exception(
            "submit_order_to_broker_task.persist_failed order_id=%s err=%s",
            order_id, exc,
        )
        # On ne peut PAS revert le broker call ; on log et on signale
        return {"ok": False, "err": f"persist_failed: {exc}"}

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


def _mark_failed_and_release(order, reason: str):
    """
    Met l'ordre en FAILED et libère le cash lock (LIVE only).
    """
    from portfolio.services import PortfolioAccountingService
    if order.mode == "LIVE":
        try:
            PortfolioAccountingService.release_cash_from_order(
                portfolio=order.portfolio,
                amount=order.approved_notional,
                reference_type="ORDER",
                reference_id=str(order.id),
            )
        except Exception:
            pass

    order.status = "FAILED"
    order.execution_notes = (order.execution_notes or "") + f"\n{reason}"
    order.save(update_fields=["status", "execution_notes", "updated_at"])


def _set_order_field(order, field, value):
    if value is not None:
        setattr(order, field, str(value))