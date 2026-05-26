from __future__ import annotations

import logging
from decimal import Decimal

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from portfolio.models import Portfolio
from risk.models import (
    RiskProfile,
    DailyRiskState,
    WeeklyRiskState,
    KillSwitchEvent,
)

logger = logging.getLogger(__name__)


def _to_decimal(value, default: str = "0") -> Decimal:
    try:
        if value is None or value == "":
            return Decimal(default)
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


@shared_task(name="risk.tasks.refresh_daily_risk_states_task")
def refresh_daily_risk_states_task():
    """
    Rafraîchit les états de risque journaliers pour tous les portefeuilles actifs.
    """
    today = timezone.localdate()
    refreshed_daily = 0

    portfolios = (
        Portfolio.objects
        .filter(is_active=True, broker_account__is_active=True)
        .select_related("broker_account")
    )

    with transaction.atomic():
        for portfolio in portfolios:
            equity = _to_decimal(getattr(portfolio, "equity", 0), "0")
            balance = _to_decimal(getattr(portfolio, "current_balance", 0), "0")
            unrealized = _to_decimal(getattr(portfolio, "unrealized_pnl", 0), "0")
            realized = _to_decimal(getattr(portfolio, "realized_pnl", 0), "0")

            daily_state, created = DailyRiskState.objects.get_or_create(
                portfolio=portfolio,
                day=today,
                defaults={
                    "equity_open": balance,
                    "equity_current": equity,
                },
            )

            if created and not daily_state.equity_open:
                daily_state.equity_open = balance

            loss_amount = Decimal("0.00")
            if realized < 0:
                loss_amount += abs(realized)
            if unrealized < 0:
                loss_amount += abs(unrealized)

            daily_state.equity_current = equity
            daily_state.realized_pnl = realized
            daily_state.unrealized_pnl = unrealized
            daily_state.total_loss_amount = loss_amount

            if daily_state.equity_open and daily_state.equity_open > 0:
                daily_state.total_loss_percent = (loss_amount / daily_state.equity_open) * Decimal("100")
            else:
                daily_state.total_loss_percent = Decimal("0.00")

            daily_state.open_positions_count = portfolio.positions.filter(status="OPEN").count()
            daily_state.save()

            refreshed_daily += 1

    logger.info(
        "Rafraîchissement des états journaliers terminé",
        extra={"daily_refreshed": refreshed_daily},
    )

    return {
        "daily_refreshed": refreshed_daily,
    }


@shared_task(name="risk.tasks.refresh_weekly_risk_states_task")
def refresh_weekly_risk_states_task():
    """
    Rafraîchit les états de risque hebdomadaires pour tous les portefeuilles actifs.
    """
    today = timezone.localdate()
    week_start = today - timezone.timedelta(days=today.weekday())
    refreshed_weekly = 0

    portfolios = (
        Portfolio.objects
        .filter(is_active=True, broker_account__is_active=True)
        .select_related("broker_account")
    )

    with transaction.atomic():
        for portfolio in portfolios:
            equity = _to_decimal(getattr(portfolio, "equity", 0), "0")
            balance = _to_decimal(getattr(portfolio, "current_balance", 0), "0")
            unrealized = _to_decimal(getattr(portfolio, "unrealized_pnl", 0), "0")
            realized = _to_decimal(getattr(portfolio, "realized_pnl", 0), "0")

            weekly_state, created = WeeklyRiskState.objects.get_or_create(
                portfolio=portfolio,
                week_start=week_start,
                defaults={
                    "equity_open": balance,
                    "equity_current": equity,
                },
            )

            if created and not weekly_state.equity_open:
                weekly_state.equity_open = balance

            loss_amount = Decimal("0.00")
            if realized < 0:
                loss_amount += abs(realized)
            if unrealized < 0:
                loss_amount += abs(unrealized)

            weekly_state.equity_current = equity
            weekly_state.realized_pnl = realized
            weekly_state.unrealized_pnl = unrealized
            weekly_state.total_loss_amount = loss_amount

            if weekly_state.equity_open and weekly_state.equity_open > 0:
                weekly_state.total_loss_percent = (loss_amount / weekly_state.equity_open) * Decimal("100")
            else:
                weekly_state.total_loss_percent = Decimal("0.00")

            weekly_state.save()

            refreshed_weekly += 1

    logger.info(
        "Rafraîchissement des états hebdomadaires terminé",
        extra={"weekly_refreshed": refreshed_weekly},
    )

    return {
        "weekly_refreshed": refreshed_weekly,
    }


@shared_task(name="risk.tasks.auto_enforce_kill_switch_task")
def auto_enforce_kill_switch_task():
    """
    Active automatiquement le kill switch métier quand une limite de risque
    est franchie.

    Règles gérées :
    - drawdown portefeuille >= max_drawdown du RiskProfile
    - état journalier déjà bloqué / kill switch déclenché
    - état hebdomadaire déjà bloqué / kill switch déclenché

    Effets :
    - création d'un KillSwitchEvent actif s'il n'en existe pas déjà un équivalent
    - marquage des DailyRiskState / WeeklyRiskState
    """
    now = timezone.now()
    checked = 0
    triggered = 0
    skipped = 0

    profiles = (
        RiskProfile.objects
        .select_related("portfolio", "user")
        .filter(is_active=True, kill_switch_enabled=True)
        .order_by("portfolio_id", "-is_default", "name")
    )

    for profile in profiles:
        checked += 1
        portfolio = getattr(profile, "portfolio", None)

        if portfolio is None:
            skipped += 1
            continue

        current_drawdown = _to_decimal(getattr(portfolio, "current_drawdown_percent", 0), "0")
        max_drawdown = _to_decimal(getattr(profile, "max_drawdown", 0), "0")

        today = now.date()
        week_start = today - timezone.timedelta(days=today.weekday())

        daily_state = (
            DailyRiskState.objects
            .filter(portfolio=portfolio, day=today)
            .order_by("-created_at")
            .first()
        )

        weekly_state = (
            WeeklyRiskState.objects
            .filter(portfolio=portfolio, week_start=week_start)
            .order_by("-created_at")
            .first()
        )

        should_trigger = False
        reason_code = ""
        reason = ""
        payload = {
            "portfolio_id": portfolio.id,
            "risk_profile_id": profile.id,
            "current_drawdown_percent": float(current_drawdown),
            "max_drawdown_percent": float(max_drawdown),
        }

        if max_drawdown > 0 and current_drawdown >= max_drawdown:
            should_trigger = True
            reason_code = "MAX_DRAWDOWN_BREACH"
            reason = (
                f"Drawdown portefeuille dépassé : {current_drawdown}% "
                f">= seuil autorisé {max_drawdown}%."
            )

        elif daily_state and (
            daily_state.kill_switch_triggered or daily_state.blocked_new_positions
        ):
            should_trigger = True
            reason_code = "DAILY_RISK_BREACH"
            reason = (
                "Le contrôle de risque journalier a déclenché un blocage "
                "des nouvelles positions."
            )
            payload["daily_risk_state_id"] = daily_state.id

        elif weekly_state and (
            weekly_state.kill_switch_triggered or weekly_state.blocked_new_positions
        ):
            should_trigger = True
            reason_code = "WEEKLY_RISK_BREACH"
            reason = (
                "Le contrôle de risque hebdomadaire a déclenché un blocage "
                "des nouvelles positions."
            )
            payload["weekly_risk_state_id"] = weekly_state.id

        if not should_trigger:
            continue

        with transaction.atomic():
            existing_event = (
                KillSwitchEvent.objects
                .filter(
                    portfolio=portfolio,
                    risk_profile=profile,
                    reason_code=reason_code,
                    is_active=True,
                )
                .order_by("-triggered_at")
                .first()
            )

            if existing_event:
                skipped += 1
                continue

            KillSwitchEvent.objects.create(
                portfolio=portfolio,
                risk_profile=profile,
                reason_code=reason_code,
                reason=reason,
                triggered_at=now,
                is_active=True,
                payload=payload,
            )

            if daily_state and not daily_state.kill_switch_triggered:
                daily_state.kill_switch_triggered = True
                daily_state.blocked_new_positions = True
                daily_payload = daily_state.payload or {}
                daily_payload["kill_switch_reason_code"] = reason_code
                daily_payload["kill_switch_reason"] = reason
                daily_state.payload = daily_payload
                daily_state.save(update_fields=[
                    "kill_switch_triggered",
                    "blocked_new_positions",
                    "payload",
                    "updated_at",
                ])

            if weekly_state and not weekly_state.kill_switch_triggered:
                weekly_state.kill_switch_triggered = True
                weekly_state.blocked_new_positions = True
                weekly_payload = weekly_state.payload or {}
                weekly_payload["kill_switch_reason_code"] = reason_code
                weekly_payload["kill_switch_reason"] = reason
                weekly_state.payload = weekly_payload
                weekly_state.save(update_fields=[
                    "kill_switch_triggered",
                    "blocked_new_positions",
                    "payload",
                    "updated_at",
                ])

            triggered += 1

            logger.warning(
                "Kill switch activé automatiquement",
                extra={
                    "portfolio_id": portfolio.id,
                    "risk_profile_id": profile.id,
                    "reason_code": reason_code,
                    "drawdown": float(current_drawdown),
                    "max_drawdown": float(max_drawdown),
                },
            )

    return {
        "checked": checked,
        "triggered": triggered,
        "skipped": skipped,
    }