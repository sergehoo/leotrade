"""
Assistant actionnable — intentions, garde-fous, confirmation, exécution.

Couverture :
  1. Moteur d'intentions : détection déterministe + extraction d'entités.
  2. Garde-fous : KYC (LIVE), broker inactif, kill switch, fonds insuffisants.
  3. prepare_trade_execution → AssistantActionRequest WAITING (résumé + risk).
  4. Confirmation PAPER : exécution via TradeIdeaExecutionService (mocké),
     statut EXECUTED, notification créée. Refus Risk Engine → pas de requête.
  5. LIVE : DOUBLE confirmation obligatoire.
  6. Annulation, expiration, jeton invalide.
  7. API REST : action-requests, confirm, cancel, tools, command — ownership.
"""

from datetime import timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.utils import timezone

from ai_assistant.models import AssistantActionRequest
from ai_assistant.services_actions import (
    AssistantActionService,
    AssistantConfirmationService,
)
from ai_assistant.services_conversation import ConversationService
from ai_assistant.services_guards import AssistantRiskValidationService
from ai_assistant.services_intent import AssistantIntentService, Intent
from ai_assistant.services_tools import AssistantToolRegistry


# ─────────────────────────────────────────────────────────────────────────────
#  Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def conversation(db, user):
    return ConversationService.get_or_create_for_context(user, {})


@pytest.fixture
def trade_idea(db, user, portfolio_paper):
    from market.models import Asset, Timeframe
    from trading.models import TradeIdea

    asset = Asset.objects.create(
        symbol="R_75", name="Volatility 75", asset_class="SYNTHETIC",
        exchange="DERIV", is_active=True,
    )
    tf, _ = Timeframe.objects.get_or_create(code="5m", defaults={"minutes": 5})
    return TradeIdea.objects.create(
        user=user, asset=asset, timeframe=tf,
        symbol="R_75", direction="BUY",
        entry_price=Decimal("100"), stop_loss=Decimal("95"),
        take_profit=Decimal("110"), expected_rr=2.0,
        confidence_score=0.8, setup_score=0.7, risk_score=0.3,
        reward_score=0.75, overall_score=0.78, status="NEW",
    )


RISK_OK = {"decision": "APPROVE", "approved_stake": "25", "expected_loss": "5",
           "expected_gain": "10", "risk_reward_ratio": "2.0",
           "blocking_reason": "", "block_code": "", "block_severity": ""}


def _prepare(user, conversation, entities):
    with mock.patch.object(
        AssistantRiskValidationService, "risk_preview", return_value=RISK_OK,
    ):
        return AssistantToolRegistry.run(
            "prepare_trade_execution", user, conversation, entities,
        )


# ─────────────────────────────────────────────────────────────────────────────
#  1. Moteur d'intentions
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("Trouve-moi les meilleures opportunités du moment", Intent.ASK_MARKET_OPPORTUNITY),
    ("explique-moi cette opportunité", Intent.EXPLAIN_TRADE_IDEA),
    ("Valide ce trade", Intent.APPROVE_TRADE_IDEA),
    ("rejette cette idée", Intent.REJECT_TRADE_IDEA),
    ("Prépare une position sur BTC avec 20 USDT", Intent.PREPARE_TRADE),
    ("Exécute cette opportunité en paper", Intent.PREPARE_TRADE),
    ("oui je confirme", Intent.CONFIRM_TRADE_EXECUTION),
    ("non", Intent.CANCEL_ACTION),
    ("Annule cet ordre", Intent.CANCEL_ORDER),
    ("Ferme ma position BTC", Intent.CLOSE_POSITION),
    ("Réduis ma position ETH de 50%", Intent.REDUCE_POSITION),
    ("Coupe toutes les positions perdantes", Intent.CLOSE_POSITION),
    ("synchronise mon portefeuille", Intent.SYNC_PORTFOLIO),
    ("teste la connexion broker", Intent.TEST_BROKER),
    ("Active le kill switch", Intent.ACTIVATE_KILL_SWITCH),
    ("Désactive le live trading", Intent.DISABLE_AUTO_TRADING),
    ("analyse mon portefeuille", Intent.PORTFOLIO_ANALYSIS),
    ("où en est mon risque ?", Intent.RISK_ANALYSIS),
    ("quelle est ta couleur préférée ?", Intent.GENERAL_CHAT),
])
def test_intent_detection(text, expected):
    assert AssistantIntentService.detect(text).intent == expected


def test_entity_extraction():
    d = AssistantIntentService.detect("Prépare une position sur BTC avec 20 USDT en live")
    assert d.entities["symbol"] == "BTCUSDT"
    assert d.entities["amount"] == 20.0
    assert d.entities["mode"] == "LIVE"

    d = AssistantIntentService.detect("Réduis ma position ETH de 50%")
    assert d.entities["symbol"] == "ETHUSDT"
    assert d.entities["percent"] == 50

    d = AssistantIntentService.detect("exécute l'idée #145 avec 25 usdt")
    assert d.entities["ref_id"] == 145
    assert d.entities["amount"] == 25.0


# ─────────────────────────────────────────────────────────────────────────────
#  2. Garde-fous
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_guard_kyc_blocks_live_only(user):
    assert AssistantRiskValidationService.check_kyc(user, "PAPER").ok
    blocked = AssistantRiskValidationService.check_kyc(user, "LIVE")
    assert not blocked.ok and blocked["code"] == "KYC_REQUIRED"


@pytest.mark.django_db
def test_guard_broker_inactive(broker_paper):
    broker_paper.is_active = False
    result = AssistantRiskValidationService.check_broker(broker_paper)
    assert not result.ok and result["code"] == "BROKER_INACTIVE"


@pytest.mark.django_db
def test_guard_insufficient_funds(portfolio_paper):
    result = AssistantRiskValidationService.check_funds(portfolio_paper, 999999)
    assert not result.ok and result["code"] == "INSUFFICIENT_FUNDS"


@pytest.mark.django_db
def test_guard_kill_switch(portfolio_live, risk_profile_live, user, conversation, trade_idea):
    from risk.services import RiskGuardService

    RiskGuardService.trigger_kill_switch(
        portfolio_live, risk_profile_live, "MANUAL", "test",
    )
    result = AssistantRiskValidationService.check_kill_switch(portfolio_live)
    assert not result.ok and result["code"] == "KILL_SWITCH_ACTIVE"


# ─────────────────────────────────────────────────────────────────────────────
#  3-4. Préparation + confirmation PAPER
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_prepare_trade_creates_waiting_request(user, conversation, trade_idea, portfolio_paper):
    result = _prepare(user, conversation, {"ref_id": trade_idea.id, "amount": 25})

    assert result["ok"] is True
    req = AssistantActionRequest.objects.get(user=user)
    assert req.status == "WAITING_CONFIRMATION"
    assert req.action_type == "EXECUTE_TRADE_IDEA"
    assert req.target_id == trade_idea.id
    assert req.mode == "PAPER" and req.requires_double_confirmation is False
    assert "R_75" in req.summary and req.risk_summary["decision"] == "APPROVE"
    assert "confirme" in result["reply"].lower()


@pytest.mark.django_db
def test_prepare_without_amount_asks_for_it(user, conversation, trade_idea, portfolio_paper):
    result = _prepare(user, conversation, {"ref_id": trade_idea.id})
    assert result["ok"] is False
    assert "montant" in result["reply"].lower()
    assert AssistantActionRequest.objects.count() == 0


@pytest.mark.django_db
def test_risk_engine_block_prevents_request(user, conversation, trade_idea, portfolio_paper):
    with mock.patch.object(
        AssistantRiskValidationService, "risk_preview",
        return_value={"decision": "BLOCK", "blocking_reason": "perte max atteinte"},
    ):
        result = AssistantToolRegistry.run(
            "prepare_trade_execution", user, conversation,
            {"ref_id": trade_idea.id, "amount": 25},
        )
    assert result["ok"] is False
    assert "Risk Engine" in result["reply"]
    assert AssistantActionRequest.objects.count() == 0


class _FakeOrder:
    id = 4242
    status = "SUBMITTED"
    symbol = "R_75"
    side = "BUY"


@pytest.mark.django_db
def test_confirm_executes_paper_trade(user, conversation, trade_idea, portfolio_paper):
    _prepare(user, conversation, {"ref_id": trade_idea.id, "amount": 25})
    req = AssistantActionRequest.objects.get(user=user)

    with mock.patch(
        "trading.services.trade_idea_execution.TradeIdeaExecutionService.execute",
        return_value={"order": _FakeOrder(), "approval": None, "risk_decision": None},
    ) as execute:
        outcome = AssistantConfirmationService.confirm(user, req.id)

    assert outcome["ok"] is True and outcome["executed"] is True
    assert "SUBMITTED" in outcome["message"]
    execute.assert_called_once()

    req.refresh_from_db()
    assert req.status == "EXECUTED"
    assert req.result["order_id"] == 4242

    # Notification émise
    from notifications.models import Notification
    assert Notification.objects.filter(
        user=user, payload__action_request_id=req.id,
    ).exists()


# ─────────────────────────────────────────────────────────────────────────────
#  5. Double confirmation LIVE
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_live_requires_double_confirmation(user, conversation, trade_idea):
    req = AssistantActionService.create_request(
        user=user, conversation=conversation,
        intent="PREPARE_TRADE", action_type="EXECUTE_TRADE_IDEA",
        target_type="TradeIdea", target_id=trade_idea.id,
        mode="LIVE", summary="trade LIVE",
        payload={"portfolio_id": 1, "broker_account_id": 1, "stake_amount": "25"},
    )
    assert req.requires_double_confirmation is True

    first = AssistantConfirmationService.confirm(user, req.id)
    assert first["ok"] is True and first["executed"] is False
    assert "SECONDE" in first["message"]
    req.refresh_from_db()
    assert req.status == "CONFIRMED" and req.confirmations_received == 1

    with mock.patch(
        "trading.services.trade_idea_execution.TradeIdeaExecutionService.execute",
        return_value={"order": _FakeOrder(), "approval": None, "risk_decision": None},
    ):
        second = AssistantConfirmationService.confirm(user, req.id)
    assert second["executed"] is True
    req.refresh_from_db()
    assert req.status == "EXECUTED" and req.confirmations_received == 2


# ─────────────────────────────────────────────────────────────────────────────
#  6. Annulation / expiration / jeton
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_cancel_and_expiry_and_token(user, conversation, trade_idea, portfolio_paper):
    _prepare(user, conversation, {"ref_id": trade_idea.id, "amount": 25})
    req = AssistantActionRequest.objects.get(user=user)

    # Jeton invalide refusé
    bad = AssistantConfirmationService.confirm(user, req.id, token="mauvais")
    assert bad["ok"] is False and "Jeton" in bad["message"]

    # Annulation
    cancelled = AssistantConfirmationService.cancel(user, req.id)
    assert cancelled["ok"] is True
    req.refresh_from_db()
    assert req.status == "CANCELLED"

    # Expiration
    req2 = _prepare(user, conversation, {"ref_id": trade_idea.id, "amount": 25})
    pending = AssistantActionRequest.objects.filter(status="WAITING_CONFIRMATION").get()
    AssistantActionRequest.objects.filter(pk=pending.pk).update(
        expires_at=timezone.now() - timedelta(minutes=1),
    )
    expired = AssistantConfirmationService.confirm(user, pending.id)
    assert expired["ok"] is False and "expirée" in expired["message"].lower()
    pending.refresh_from_db()
    assert pending.status == "EXPIRED"


@pytest.mark.django_db
def test_ownership_on_confirmation(user, conversation, trade_idea, portfolio_paper):
    from django.contrib.auth import get_user_model

    _prepare(user, conversation, {"ref_id": trade_idea.id, "amount": 25})
    req = AssistantActionRequest.objects.get(user=user)

    intruder = get_user_model().objects.create_user(username="intrus3", password="x")
    result = AssistantConfirmationService.confirm(intruder, req.id)
    assert result["ok"] is False and result["request"] is None


# ─────────────────────────────────────────────────────────────────────────────
#  7. API REST
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_api_tools_catalog(client, user):
    client.force_login(user)
    resp = client.get("/assistant/api/tools/")
    assert resp.status_code == 200
    names = {t["name"] for t in resp.json()["tools"]}
    assert {"find_trade_ideas", "prepare_trade_execution", "close_position",
            "activate_kill_switch"} <= names


@pytest.mark.django_db
def test_api_command_prepares_then_confirms(client, user, trade_idea, portfolio_paper):
    client.force_login(user)

    with mock.patch.object(
        AssistantRiskValidationService, "risk_preview", return_value=RISK_OK,
    ):
        resp = client.post(
            "/assistant/api/command/",
            {"text": f"exécute l'idée #{trade_idea.id} avec 25 USDT"},
            content_type="application/json",
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["intent"] == "PREPARE_TRADE"
    assert body["action_request"]["status"] == "WAITING_CONFIRMATION"
    request_id = body["action_request"]["id"]

    with mock.patch(
        "trading.services.trade_idea_execution.TradeIdeaExecutionService.execute",
        return_value={"order": _FakeOrder(), "approval": None, "risk_decision": None},
    ):
        resp = client.post(
            f"/assistant/api/action-requests/{request_id}/confirm/",
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert resp.json()["request"]["status"] == "EXECUTED"

    # Liste filtrable
    resp = client.get("/assistant/api/action-requests/?status=executed")
    assert resp.json()["count"] == 1


@pytest.mark.django_db
def test_api_action_requests_isolated(client, user, conversation, trade_idea, portfolio_paper):
    from django.contrib.auth import get_user_model

    client.force_login(user)
    _prepare(user, conversation, {"ref_id": trade_idea.id, "amount": 25})
    req = AssistantActionRequest.objects.get(user=user)

    other = get_user_model().objects.create_user(username="other9", password="x")
    client.force_login(other)
    assert client.get("/assistant/api/action-requests/").json()["count"] == 0
    resp = client.post(f"/assistant/api/action-requests/{req.id}/confirm/",
                       content_type="application/json")
    assert resp.status_code == 400
