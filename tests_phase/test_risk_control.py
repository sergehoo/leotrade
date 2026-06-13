"""
Module Risk Control — pages réelles, API, services, audit, sécurité.

Couverture :
  1. Les routes /risk/* existent vraiment (plus de 404) — pages + API.
  2. RiskControlService : snapshot profil/drawdown/kill switch, états, décisions.
  3. KillSwitchService : activation/désactivation + RiskAuditLog + notification.
  4. RiskSettingsUpdateService : modification auditée, champs non éditables ignorés.
  5. EmergencyPositionService : fermeture via ordre opposé (ExecutionOrchestrator
     mocké), broker inactif bloqué, close-all-losing ne ferme que les perdantes.
  6. API : confirmations requises, double confirmation LIVE/close-all, ownership.
"""

from decimal import Decimal
from unittest import mock

import pytest
from django.urls import reverse

from risk.models import RiskAuditLog
from risk.services_control import (
    EmergencyPositionService,
    KillSwitchService,
    RiskControlService,
    RiskSettingsUpdateService,
)

pytestmark = pytest.mark.django_db


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def asset(db):
    from market.models import Asset
    return Asset.objects.create(
        symbol="R_75", name="Volatility 75", asset_class="SYNTHETIC",
        exchange="DERIV", is_active=True,
    )


def _make_position(portfolio, broker, asset, *, side="LONG", qty="10",
                   entry="100", current="100", pnl="0"):
    from portfolio.models import Position
    return Position.objects.create(
        portfolio=portfolio, broker_account=broker, asset=asset,
        symbol=asset.symbol, side=side, quantity=Decimal(qty),
        entry_price=Decimal(entry), average_entry_price=Decimal(entry),
        current_price=Decimal(current), unrealized_pnl=Decimal(pnl),
        status="OPEN", source="MANUAL",
    )


class _FakeOrder:
    def __init__(self, oid=999):
        self.id = oid
        self.status = "SUBMITTED"


# ── 1. Routes réelles ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "risk:home", "risk:profile", "risk:kill-switch",
    "risk:states", "risk:decisions", "risk:emergency-actions",
])
def test_risk_pages_render(client, user, name):
    client.force_login(user)
    resp = client.get(reverse(name))
    assert resp.status_code == 200


def test_risk_api_profile_returns_real_data(client, user, portfolio_paper):
    client.force_login(user)
    resp = client.get(reverse("risk:api-profile"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["portfolio"]["id"] == portfolio_paper.id
    assert data["portfolio"]["mode"] in ("PAPER", "LIVE")
    assert "max_daily_loss" in data["profile"]
    assert "kill_switch" in data


def test_risk_api_requires_auth(client):
    resp = client.get(reverse("risk:api-profile"))
    assert resp.status_code in (302, 401, 403)


# ── 2. RiskControlService ───────────────────────────────────────────────────────

def test_profile_snapshot_structure(portfolio_paper):
    snap = RiskControlService.profile_snapshot(portfolio_paper)
    assert set(snap) == {"portfolio", "profile", "drawdown", "kill_switch"}
    assert snap["kill_switch"]["active"] is False


# ── 3. KillSwitchService ────────────────────────────────────────────────────────

def test_kill_switch_activate_deactivate_audits(user, portfolio_paper):
    res = KillSwitchService.activate(user=user, portfolio=portfolio_paper, reason="test")
    assert res["ok"] and not res.get("already_active")
    from risk.services import RiskGuardService
    assert RiskGuardService.has_active_kill_switch(portfolio_paper) is True
    assert RiskAuditLog.objects.filter(
        portfolio=portfolio_paper, action="KILL_SWITCH_ACTIVATE",
    ).exists()

    # Idempotent
    res2 = KillSwitchService.activate(user=user, portfolio=portfolio_paper)
    assert res2.get("already_active") is True

    res3 = KillSwitchService.deactivate(user=user, portfolio=portfolio_paper)
    assert res3["ok"] and not res3.get("already_inactive")
    assert RiskGuardService.has_active_kill_switch(portfolio_paper) is False
    assert RiskAuditLog.objects.filter(
        portfolio=portfolio_paper, action="KILL_SWITCH_DEACTIVATE",
    ).exists()


def test_kill_switch_api_activate(client, user, portfolio_paper):
    client.force_login(user)
    resp = client.post(reverse("risk:api-kill-switch-activate"),
                       {"reason": "manuel"}, content_type="application/json")
    assert resp.status_code == 200 and resp.json()["ok"]
    from risk.services import RiskGuardService
    assert RiskGuardService.has_active_kill_switch(portfolio_paper) is True


# ── 4. RiskSettingsUpdateService ─────────────────────────────────────────────────

def test_settings_update_audited(user, portfolio_paper):
    res = RiskSettingsUpdateService.update(
        user=user, portfolio=portfolio_paper,
        changes={"max_daily_loss": "7.5", "max_open_positions": 8,
                 "non_editable_field": "x"},
    )
    assert res["ok"]
    assert Decimal(res["applied"]["max_daily_loss"]) == Decimal("7.5")
    assert "non_editable_field" not in res["applied"]

    from risk.services import RiskGuardService
    profile = RiskGuardService.get_default_profile(portfolio_paper)
    assert str(profile.max_daily_loss) == "7.5000"
    assert profile.max_open_positions == 8

    log = RiskAuditLog.objects.filter(
        portfolio=portfolio_paper, action="RISK_SETTINGS_UPDATE",
    ).first()
    assert log is not None
    assert log.before["max_daily_loss"] != log.after["max_daily_loss"]


def test_settings_update_via_api_patch(client, user, portfolio_paper):
    client.force_login(user)
    resp = client.patch(
        reverse("risk:api-profile"),
        {"changes": {"max_drawdown": "12"}},
        content_type="application/json",
    )
    assert resp.status_code == 200 and resp.json()["ok"]


# ── 5. EmergencyPositionService ──────────────────────────────────────────────────

def test_close_position_via_orchestrator(user, portfolio_paper, broker_paper, asset):
    pos = _make_position(portfolio_paper, broker_paper, asset)

    with mock.patch("execution.services.ExecutionOrchestrator.create_order",
                    return_value=_FakeOrder()) as create, \
         mock.patch("execution.services.ExecutionOrchestrator.submit_order",
                    return_value=_FakeOrder()) as submit:
        res = EmergencyPositionService.close_position(
            user=user, portfolio=portfolio_paper, position_id=pos.id,
        )

    assert res["ok"] is True
    # Ordre OPPOSÉ (position LONG → SELL)
    assert create.call_args.kwargs["side"] == "SELL"
    submit.assert_called_once()
    assert RiskAuditLog.objects.filter(
        portfolio=portfolio_paper, action="EMERGENCY_CLOSE_POSITION",
    ).exists()


def test_close_blocked_when_broker_inactive(user, portfolio_paper, broker_paper, asset):
    broker_paper.is_active = False
    broker_paper.save(update_fields=["is_active"])
    pos = _make_position(portfolio_paper, broker_paper, asset)

    res = EmergencyPositionService.close_position(
        user=user, portfolio=portfolio_paper, position_id=pos.id,
    )
    assert res["ok"] is False
    assert "broker" in res["results"][0]["message"].lower()


def test_close_all_losing_only_closes_losers(user, portfolio_paper, broker_paper, asset):
    from market.models import Asset
    asset2 = Asset.objects.create(symbol="R_50", name="V50", asset_class="SYNTHETIC",
                                  exchange="DERIV", is_active=True)
    winner = _make_position(portfolio_paper, broker_paper, asset, pnl="50")
    loser = _make_position(portfolio_paper, broker_paper, asset2, pnl="-30")

    with mock.patch("execution.services.ExecutionOrchestrator.create_order",
                    return_value=_FakeOrder()), \
         mock.patch("execution.services.ExecutionOrchestrator.submit_order",
                    return_value=_FakeOrder()):
        res = EmergencyPositionService.close_all_losing(
            user=user, portfolio=portfolio_paper,
        )

    assert res["ok"] is True
    closed_ids = {r["position_id"] for r in res["results"]}
    assert loser.id in closed_ids and winner.id not in closed_ids


def test_close_all_empty_is_safe(user, portfolio_paper):
    res = EmergencyPositionService.close_all(user=user, portfolio=portfolio_paper)
    assert res["ok"] is True and res["results"] == []


# ── 6. API confirmations / double confirmation / ownership ───────────────────────

def test_emergency_close_position_requires_confirm(client, user, portfolio_paper, broker_paper, asset):
    client.force_login(user)
    pos = _make_position(portfolio_paper, broker_paper, asset)
    # Sans confirm → refusé
    resp = client.post(reverse("risk:api-emergency-close-position"),
                       {"position_id": pos.id}, content_type="application/json")
    assert resp.status_code == 400 and "onfirm" in resp.json()["message"]


def test_emergency_close_all_requires_double_confirm(client, user, portfolio_paper):
    client.force_login(user)
    # confirm seul ne suffit pas pour close-all
    resp = client.post(reverse("risk:api-emergency-close-all"),
                       {"confirm": True}, content_type="application/json")
    assert resp.status_code == 400
    assert resp.json().get("requires_double_confirmation") is True


def test_live_close_position_requires_double(client, user, portfolio_live, asset):
    from portfolio.models import Position
    pos = Position.objects.create(
        portfolio=portfolio_live, broker_account=portfolio_live.broker_account,
        asset=asset, symbol=asset.symbol, side="LONG", quantity=Decimal("1"),
        entry_price=Decimal("100"), average_entry_price=Decimal("100"),
        current_price=Decimal("100"), status="OPEN", source="MANUAL",
    )
    client.force_login(user)
    # LIVE : confirm seul → exige confirm_live
    resp = client.post(reverse("risk:api-emergency-close-position"),
                       {"position_id": pos.id, "confirm": True},
                       content_type="application/json")
    assert resp.status_code == 400
    assert resp.json().get("requires_double_confirmation") is True


def test_emergency_ownership_isolation(client, portfolio_paper, broker_paper, asset):
    from django.contrib.auth import get_user_model
    pos = _make_position(portfolio_paper, broker_paper, asset)
    other = get_user_model().objects.create_user(username="intrus_risk", password="x")
    client.force_login(other)
    # L'intrus n'a pas de portefeuille → 404, et ne peut pas viser celui d'autrui
    resp = client.post(reverse("risk:api-emergency-close-position"),
                       {"position_id": pos.id, "confirm": True},
                       content_type="application/json")
    assert resp.status_code == 404
