"""
Tâches Celery du module notifications.

- send_notification_task          : envoi multicanal d'une notification
- retry_failed_notifications_task : rejoue les livraisons FAILED (backoff par beat)
- send_daily_trading_report_task  : rapport quotidien (données réelles)
- send_weekly_trading_report_task : rapport hebdo de performance
- cleanup_old_notifications_task  : purge des notifications lues anciennes
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from celery import shared_task
from django.utils import timezone

log = logging.getLogger("leotrade.notifications.tasks")

MAX_DELIVERY_RETRIES = 3
CLEANUP_READ_AFTER_DAYS = 60
CLEANUP_UNREAD_AFTER_DAYS = 180


@shared_task(
    name="notifications.tasks.send_notification_task",
    bind=True,
    max_retries=2,
    default_retry_delay=10,
)
def send_notification_task(self, notification_id: int):
    """Envoie une notification sur tous ses canaux. Idempotent : ne renvoie
    pas une notification déjà SENT."""
    from notifications.models import Notification
    from notifications.services import NotificationService

    notification = Notification.objects.filter(pk=notification_id).first()
    if notification is None:
        return {"skipped": "not_found"}
    if notification.status in ("SENT", "SUPPRESSED"):
        return {"skipped": notification.status}

    try:
        return NotificationService.dispatch(notification)
    except Exception as exc:
        log.exception("send_notification_task.failed id=%s", notification_id)
        raise self.retry(exc=exc)


@shared_task(name="notifications.tasks.retry_failed_notifications_task")
def retry_failed_notifications_task(max_age_hours: int = 24, batch: int = 100):
    """Rejoue les livraisons FAILED récentes (retry_count < MAX).
    Cadencée par beat : le backoff effectif = intervalle du beat."""
    from notifications.events import Channel
    from notifications.models import NotificationDeliveryLog
    from notifications.services.core import CHANNEL_SERVICES
    from notifications.services.preferences import NotificationPreferenceService

    since = timezone.now() - timedelta(hours=max_age_hours)
    failed = (
        NotificationDeliveryLog.objects
        .filter(status="FAILED", retry_count__lt=MAX_DELIVERY_RETRIES, created_at__gte=since)
        .select_related("notification", "notification__user")
        .order_by("created_at")[:batch]
    )

    retried = recovered = 0
    for entry in failed:
        service = CHANNEL_SERVICES.get(entry.channel)
        if service is None:
            continue
        retried += 1
        entry.retry_count += 1
        entry.status = "RETRYING"
        entry.save(update_fields=["retry_count", "status", "updated_at"])

        pref = NotificationPreferenceService.get_or_create(entry.notification.user)
        try:
            result = service.send(entry.notification, language=pref.preferred_language or "fr")
        except Exception as exc:
            result = {"ok": False, "error": str(exc)[:1000], "response": {}, "recipient": entry.recipient}

        if result.get("ok"):
            entry.status = "SENT"
            entry.sent_at = timezone.now()
            entry.error_message = ""
            recovered += 1
            notification = entry.notification
            if entry.channel not in (notification.channels_sent or []):
                notification.channels_sent = [*(notification.channels_sent or []), entry.channel]
            notification.status = "SENT" if set(notification.channels_sent) >= set(
                notification.channels_requested or []
            ) else "PARTIAL"
            notification.save(update_fields=["channels_sent", "status", "updated_at"])
        else:
            entry.status = "FAILED"
            entry.error_message = result.get("error", "")[:2000]
        entry.response_payload = result.get("response") or {}
        entry.save()

    if retried:
        log.info("retry_failed_notifications retried=%s recovered=%s", retried, recovered)
    return {"retried": retried, "recovered": recovered}


def _portfolio_day_stats(user, since) -> dict | None:
    """Statistiques de trading réelles depuis `since` (None si aucune activité)."""
    from django.db.models import Count, Q, Sum

    from execution.models import Order
    from portfolio.models import Portfolio

    orders = Order.objects.filter(user=user, created_at__gte=since)
    order_stats = orders.aggregate(
        total=Count("id"),
        filled=Count("id", filter=Q(status="FILLED")),
        rejected=Count("id", filter=Q(status="REJECTED")),
        failed=Count("id", filter=Q(status="FAILED")),
    )

    portfolios = Portfolio.objects.filter(user=user, is_active=True)
    pf = portfolios.aggregate(
        equity=Sum("equity"),
        balance=Sum("current_balance"),
        unrealized=Sum("unrealized_pnl"),
        realized=Sum("realized_pnl"),
    )

    trades = []
    try:
        from portfolio.models_trade import Trade
        trades_qs = Trade.objects.filter(portfolio__user=user, closed_at__gte=since)
        trades = list(trades_qs.values_list("realized_pnl", flat=True))
    except Exception:
        pass

    if not order_stats["total"] and not trades and not portfolios.exists():
        return None  # zéro fake data : pas d'activité → pas de rapport vide

    realized_period = sum(trades, Decimal("0")) if trades else Decimal("0")
    wins = sum(1 for p in trades if p > 0)

    return {
        "orders_total": order_stats["total"] or 0,
        "orders_filled": order_stats["filled"] or 0,
        "orders_rejected": (order_stats["rejected"] or 0) + (order_stats["failed"] or 0),
        "trades_closed": len(trades),
        "trades_won": wins,
        "realized_pnl_period": str(realized_period),
        "equity": str(pf["equity"] or Decimal("0")),
        "balance": str(pf["balance"] or Decimal("0")),
        "unrealized_pnl": str(pf["unrealized"] or Decimal("0")),
        "realized_pnl_total": str(pf["realized"] or Decimal("0")),
    }


@shared_task(name="notifications.tasks.send_daily_trading_report_task")
def send_daily_trading_report_task():
    """Rapport quotidien — uniquement aux utilisateurs avec activité réelle."""
    from django.contrib.auth import get_user_model

    from notifications.shortcuts import notify

    since = timezone.now() - timedelta(days=1)
    sent = 0
    users = get_user_model().objects.filter(
        is_active=True,
        notification_preference__reports_enabled=True,
    )
    for user in users:
        stats = _portfolio_day_stats(user, since)
        if stats is None:
            continue
        pnl = Decimal(stats["realized_pnl_period"])
        notify(
            user, "DAILY_TRADING_REPORT",
            title="Ton rapport de trading du jour",
            message=(
                f"{stats['orders_total']} ordre(s), {stats['trades_closed']} trade(s) clos "
                f"({stats['trades_won']} gagnant(s)). "
                f"PnL réalisé sur 24h : {pnl:+.2f} $. "
                f"Équité totale : {Decimal(stats['equity']):.2f} $."
            ),
            payload={"report": stats, "period": "daily"},
        )
        sent += 1
    return {"reports_sent": sent}


@shared_task(name="notifications.tasks.send_weekly_trading_report_task")
def send_weekly_trading_report_task():
    """Rapport hebdomadaire de performance."""
    from django.contrib.auth import get_user_model

    from notifications.shortcuts import notify

    since = timezone.now() - timedelta(days=7)
    sent = 0
    users = get_user_model().objects.filter(
        is_active=True,
        notification_preference__reports_enabled=True,
    )
    for user in users:
        stats = _portfolio_day_stats(user, since)
        if stats is None:
            continue
        pnl = Decimal(stats["realized_pnl_period"])
        win_rate = (
            f"{stats['trades_won'] / stats['trades_closed']:.0%}"
            if stats["trades_closed"] else "—"
        )
        notify(
            user, "WEEKLY_PERFORMANCE_REPORT",
            title="Ta performance de la semaine",
            message=(
                f"{stats['trades_closed']} trade(s) clos, win rate {win_rate}. "
                f"PnL réalisé sur 7 jours : {pnl:+.2f} $. "
                f"Équité totale : {Decimal(stats['equity']):.2f} $."
            ),
            payload={"report": stats, "period": "weekly"},
        )
        sent += 1
    return {"reports_sent": sent}


@shared_task(name="notifications.tasks.cleanup_old_notifications_task")
def cleanup_old_notifications_task():
    """Purge : notifications lues > 60 j, non lues > 180 j (logs en cascade)."""
    from notifications.models import Notification

    now = timezone.now()
    read_deleted, _ = Notification.objects.filter(
        read_at__isnull=False,
        read_at__lt=now - timedelta(days=CLEANUP_READ_AFTER_DAYS),
    ).delete()
    unread_deleted, _ = Notification.objects.filter(
        read_at__isnull=True,
        created_at__lt=now - timedelta(days=CLEANUP_UNREAD_AFTER_DAYS),
    ).delete()
    return {"read_deleted": read_deleted, "unread_deleted": unread_deleted}
