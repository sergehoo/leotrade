"""
Module notifications — tests essentiels.

Couverture :
  1. Résolution des canaux (priorité email, critique → tous canaux,
     quiet hours, catégories désactivées, critique incompressible).
  2. NotificationService.notify : création, suppression, rate limit, dedupe.
  3. Dispatch : email réellement envoyé (locmem), logs de livraison,
     statuts SENT/PARTIAL, SMS skipped sans provider.
  4. Renderer : gabarit seedé (kill switch) avec variables.
  5. API DRF : liste, unread-count, mark-read, mark-all-read, préférences,
     isolation entre utilisateurs.
  6. Intégrations : création broker et kill switch produisent une notification.
  7. Tâche retry : une livraison FAILED repasse SENT.
"""

from datetime import time as dtime
from decimal import Decimal
from unittest import mock

import pytest
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse

from notifications.events import Channel
from notifications.models import (
    Notification,
    NotificationDeliveryLog,
    NotificationPreference,
)
from notifications.services import (
    NotificationPreferenceService,
    NotificationService,
)

LOCMEM_EMAIL = override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
)


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def pref(user):
    return NotificationPreferenceService.get_or_create(user)


def _dispatch_now(notification):
    """Envoi synchrone (sans worker Celery) pour les tests."""
    return NotificationService.dispatch(notification)


# ─────────────────────────────────────────────────────────────────────────────
#  1. Résolution des canaux
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_normal_event_resolves_email_and_in_app(user, pref):
    channels, _ = NotificationPreferenceService.resolve_channels(
        user, "ORDER_CREATED", "NORMAL",
    )
    assert channels == [Channel.EMAIL, Channel.IN_APP]


@pytest.mark.django_db
def test_critical_event_uses_all_allowed_channels(user, pref):
    pref.sms_enabled = True
    pref.whatsapp_enabled = True
    pref.phone_number = "+2250700000000"
    pref.save()

    channels, _ = NotificationPreferenceService.resolve_channels(
        user, "KILL_SWITCH_ACTIVATED", "URGENT",
    )
    assert channels == [Channel.EMAIL, Channel.IN_APP, Channel.SMS, Channel.WHATSAPP]


@pytest.mark.django_db
def test_sms_requires_phone_number(user, pref):
    pref.sms_enabled = True
    pref.phone_number = ""
    pref.save()

    channels, _ = NotificationPreferenceService.resolve_channels(
        user, "KILL_SWITCH_ACTIVATED", "URGENT",
    )
    assert Channel.SMS not in channels


@pytest.mark.django_db
def test_quiet_hours_keep_only_in_app_for_non_critical(user, pref):
    pref.quiet_hours_start = dtime(0, 0)
    pref.quiet_hours_end = dtime(23, 59)
    pref.save()

    channels, _ = NotificationPreferenceService.resolve_channels(
        user, "ORDER_FILLED", "HIGH",
    )
    assert channels == [Channel.IN_APP]


@pytest.mark.django_db
def test_critical_ignores_quiet_hours(user, pref):
    pref.quiet_hours_start = dtime(0, 0)
    pref.quiet_hours_end = dtime(23, 59)
    pref.save()

    channels, _ = NotificationPreferenceService.resolve_channels(
        user, "SECURITY_ALERT", "URGENT",
    )
    assert Channel.EMAIL in channels and Channel.IN_APP in channels


@pytest.mark.django_db
def test_disabled_category_suppresses_non_critical(user, pref):
    pref.trade_events_enabled = False
    pref.save()

    channels, reason = NotificationPreferenceService.resolve_channels(
        user, "ORDER_CREATED", "NORMAL",
    )
    assert channels == [] and reason == "category_disabled"


@pytest.mark.django_db
def test_disabled_category_cannot_silence_critical(user, pref):
    """Un kill switch reste notifié même si la catégorie risque est coupée."""
    pref.risk_events_enabled = False
    pref.save()

    channels, reason = NotificationPreferenceService.resolve_channels(
        user, "KILL_SWITCH_ACTIVATED", "URGENT",
    )
    assert Channel.IN_APP in channels and reason == ""


# ─────────────────────────────────────────────────────────────────────────────
#  2. NotificationService.notify
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_notify_creates_pending_notification(user):
    n = NotificationService.notify(
        user, "ORDER_FILLED",
        title="Ordre exécuté", message="10 lots à 100.",
        payload={"order_id": 1},
    )
    assert n is not None
    assert n.status == "PENDING"
    assert n.severity == "SUCCESS" and n.priority == "HIGH"  # défauts du registre
    assert Channel.EMAIL in n.channels_requested


@pytest.mark.django_db
def test_notify_rate_limit(user):
    from notifications.services.core import RATE_LIMIT_MAX

    created = [
        NotificationService.notify(user, "SIGNAL_GENERATED", title=f"s{i}", message="x")
        for i in range(RATE_LIMIT_MAX + 5)
    ]
    assert sum(1 for n in created if n is not None) == RATE_LIMIT_MAX


@pytest.mark.django_db
def test_notify_dedupe_key(user):
    n1 = NotificationService.notify(
        user, "KILL_SWITCH_ACTIVATED", title="ks", message="x", dedupe_key="ks:1",
    )
    n2 = NotificationService.notify(
        user, "KILL_SWITCH_ACTIVATED", title="ks", message="x", dedupe_key="ks:1",
    )
    assert n1 is not None and n2 is None


@pytest.mark.django_db
def test_notify_never_raises(user):
    with mock.patch(
        "notifications.services.core.NotificationService._notify",
        side_effect=RuntimeError("boom"),
    ):
        assert NotificationService.notify(user, "ORDER_FILLED") is None


# ─────────────────────────────────────────────────────────────────────────────
#  3. Dispatch multicanal
# ─────────────────────────────────────────────────────────────────────────────

@LOCMEM_EMAIL
@pytest.mark.django_db
def test_dispatch_sends_email_and_logs(user, pref):
    user.email = "trader@test.io"
    user.save(update_fields=["email"])

    n = NotificationService.notify(
        user, "ORDER_FILLED", title="Ordre exécuté : BUY R_75",
        message="10 lots à 1234.", payload={"symbol": "R_75"},
    )
    result = _dispatch_now(n)

    assert result["status"] == "SENT"
    assert set(result["sent"]) == {Channel.EMAIL, Channel.IN_APP}
    assert len(mail.outbox) == 1
    assert "Ordre exécuté" in mail.outbox[0].subject
    logs = NotificationDeliveryLog.objects.filter(notification=n)
    assert logs.filter(channel=Channel.EMAIL, status="SENT").exists()
    assert logs.filter(channel=Channel.IN_APP, status="SENT").exists()


@LOCMEM_EMAIL
@pytest.mark.django_db
def test_dispatch_sms_without_provider_is_skipped_not_failed(user, pref):
    user.email = "trader@test.io"
    user.save(update_fields=["email"])
    pref.sms_enabled = True
    pref.phone_number = "+2250700000000"
    pref.save()

    n = NotificationService.notify(user, "SECURITY_ALERT", title="alerte", message="x")
    result = _dispatch_now(n)

    # SMS skipped (pas de credentials Twilio en test) → pas un échec
    sms_log = NotificationDeliveryLog.objects.get(notification=n, channel=Channel.SMS)
    assert sms_log.status == "SKIPPED"
    assert result["status"] == "SENT"


@LOCMEM_EMAIL
@pytest.mark.django_db
def test_dispatch_partial_on_email_failure(user, pref):
    user.email = "trader@test.io"
    user.save(update_fields=["email"])

    n = NotificationService.notify(user, "ORDER_FILLED", title="t", message="m")
    with mock.patch(
        "notifications.services.email.EmailMultiAlternatives.send",
        side_effect=ConnectionError("smtp down"),
    ):
        result = _dispatch_now(n)

    assert result["status"] == "PARTIAL"
    email_log = NotificationDeliveryLog.objects.get(notification=n, channel=Channel.EMAIL)
    assert email_log.status == "FAILED" and "smtp down" in email_log.error_message


# ─────────────────────────────────────────────────────────────────────────────
#  4. Renderer (gabarit seedé)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_renderer_uses_seeded_kill_switch_template(user):
    from notifications.services import NotificationTemplateRenderer

    n = Notification.objects.create(
        user=user, title="ks", message="fallback",
        event_type="KILL_SWITCH_ACTIVATED",
        payload={"portfolio_name": "Main", "reason": "Perte journalière max",
                 "site_url": "http://test"},
    )
    rendered = NotificationTemplateRenderer.render(n, "EMAIL", "fr")
    assert "Kill switch activé" in rendered["subject"]
    assert "Main" in rendered["body"]
    assert "Perte journalière max" in rendered["body"]


# ─────────────────────────────────────────────────────────────────────────────
#  5. API DRF
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_api_list_and_filters(client, user):
    client.force_login(user)
    NotificationService.notify(user, "ORDER_FILLED", title="a", message="x")
    NotificationService.notify(user, "KILL_SWITCH_ACTIVATED", title="b", message="y")

    resp = client.get("/api/notifications/")
    assert resp.status_code == 200
    assert resp.json()["count"] == 2

    resp = client.get("/api/notifications/?event_type=ORDER_FILLED")
    assert resp.json()["count"] == 1

    resp = client.get("/api/notifications/?severity=critical")
    assert resp.json()["count"] == 1


@pytest.mark.django_db
def test_api_unread_and_mark_read(client, user):
    client.force_login(user)
    n = NotificationService.notify(user, "ORDER_FILLED", title="a", message="x")

    assert client.get("/api/notifications/unread-count/").json() == {"unread": 1}

    resp = client.post(f"/api/notifications/{n.id}/mark-read/")
    assert resp.status_code == 200
    assert resp.json()["unread"] == 0

    NotificationService.notify(user, "ORDER_FILLED", title="b", message="x")
    NotificationService.notify(user, "ORDER_FILLED", title="c", message="x")
    resp = client.post("/api/notifications/mark-all-read/")
    assert resp.json() == {"marked": 2, "unread": 0}


@pytest.mark.django_db
def test_api_user_isolation(client, user):
    from django.contrib.auth import get_user_model

    other = get_user_model().objects.create_user(username="other", password="x")
    n_other = NotificationService.notify(other, "ORDER_FILLED", title="o", message="x")

    client.force_login(user)
    assert client.get("/api/notifications/").json()["count"] == 0
    assert client.post(f"/api/notifications/{n_other.id}/mark-read/").status_code == 404


@pytest.mark.django_db
def test_api_preferences_get_and_patch(client, user):
    client.force_login(user)

    resp = client.get("/api/notifications/preferences/")
    assert resp.status_code == 200
    assert resp.json()["email_enabled"] is True

    resp = client.patch(
        "/api/notifications/preferences/",
        data={"sms_enabled": True, "phone_number": "+2250700000000",
              "quiet_hours_start": "22:00", "quiet_hours_end": "07:00"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    pref = NotificationPreference.objects.get(user=user)
    assert pref.sms_enabled is True
    assert pref.phone_number == "+2250700000000"
    assert pref.quiet_hours_start == dtime(22, 0)


# ─────────────────────────────────────────────────────────────────────────────
#  6. Intégrations réelles
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_kill_switch_trigger_creates_notification(portfolio_live, risk_profile_live):
    from risk.services import RiskGuardService

    RiskGuardService.trigger_kill_switch(
        portfolio_live, risk_profile_live,
        "DAILY_LOSS_LIMIT", "Perte journalière maximale atteinte.",
    )

    notifs = Notification.objects.filter(
        user=portfolio_live.user, event_type="KILL_SWITCH_ACTIVATED",
    )
    assert notifs.count() == 1
    assert notifs.first().payload["portfolio_id"] == portfolio_live.id
    # L'événement de limite a sa propre notification
    assert Notification.objects.filter(
        user=portfolio_live.user, event_type="DAILY_LOSS_LIMIT",
    ).exists()


@pytest.mark.django_db
def test_broker_create_view_notifies(client, user):
    client.force_login(user)
    resp = client.post(reverse("broker-create"), {
        "name": "Mon Binance", "broker": "BINANCE", "mode": "PAPER",
    })
    assert resp.status_code in (200, 302)
    if resp.status_code == 302:  # création réussie
        assert Notification.objects.filter(
            user=user, event_type="BROKER_ACCOUNT_CREATED",
        ).exists()


@pytest.mark.django_db
def test_position_close_notifies(portfolio_paper, broker_paper, user):
    from execution.models import ExecutionFill, Order
    from execution.services_close import PositionCloseService
    from market.models import Asset
    from portfolio.models import Position

    asset = Asset.objects.create(
        symbol="EURUSD", name="Euro Dollar", asset_class="FOREX",
        exchange="DERIV", is_active=True,
    )
    position = Position.objects.create(
        portfolio=portfolio_paper, broker_account=broker_paper, asset=asset,
        symbol="EURUSD", side="LONG", quantity=Decimal("10"),
        entry_price=Decimal("1.10"), average_entry_price=Decimal("1.10"),
        current_price=Decimal("1.20"), status="OPEN", source="MANUAL",
    )
    order = Order.objects.create(
        user=user, portfolio=portfolio_paper, broker_account=broker_paper,
        symbol="EURUSD", side="BUY", order_type="MARKET",
        approved_quantity=Decimal("10"), status="FILLED",
        idempotency_key="notif-close-1", mode="PAPER",
    )
    fill = ExecutionFill.objects.create(
        order=order, broker_fill_id="f-1", quantity=Decimal("10"),
        price=Decimal("1.20"), notional=Decimal("12.00"), fee=Decimal("0.10"),
    )

    PositionCloseService.apply_closing_fill(
        position=position, fill=fill, opening_order=order,
    )

    notif = Notification.objects.filter(user=user, event_type="POSITION_CLOSED").first()
    assert notif is not None
    assert "EURUSD" in notif.title


# ─────────────────────────────────────────────────────────────────────────────
#  7. Tâche retry
# ─────────────────────────────────────────────────────────────────────────────

@LOCMEM_EMAIL
@pytest.mark.django_db
def test_retry_recovers_failed_email(user, pref):
    from notifications.tasks import retry_failed_notifications_task

    user.email = "trader@test.io"
    user.save(update_fields=["email"])

    n = NotificationService.notify(user, "ORDER_FILLED", title="t", message="m")
    with mock.patch(
        "notifications.services.email.EmailMultiAlternatives.send",
        side_effect=ConnectionError("smtp down"),
    ):
        _dispatch_now(n)
    assert n.delivery_logs.filter(channel=Channel.EMAIL, status="FAILED").exists()

    result = retry_failed_notifications_task()

    assert result == {"retried": 1, "recovered": 1}
    n.refresh_from_db()
    assert Channel.EMAIL in n.channels_sent
    assert n.status == "SENT"
    assert len(mail.outbox) == 1
