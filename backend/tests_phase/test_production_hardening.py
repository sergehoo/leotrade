from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from brokers.forms import BrokerAccountForm
from brokers.models import BrokerAccount
from ai_assistant.models import AIQuotaPayment, AIUserQuota
from ai_assistant.services import QuotaService
from portfolio.models import Portfolio
from trading.services.trade_idea_generation import TradeIdeaGenerationService
from wallet.models import Wallet, WalletTransaction
from wallet.services_v2 import WalletLedgerService


User = get_user_model()


@pytest.fixture
def account_user(db):
    return User.objects.create_user(
        username="hardening-user",
        email="hardening@example.test",
        password="strong-test-password",
    )


@pytest.fixture
def paper_portfolio(account_user):
    broker = BrokerAccount.objects.create(
        user=account_user,
        name="Paper",
        broker="BINANCE",
        mode="PAPER",
        status="ACTIVE",
    )
    return Portfolio.objects.create(
        user=account_user,
        broker_account=broker,
        name="Paper portfolio",
        is_active=True,
    )


@pytest.mark.django_db
def test_broker_form_never_decrypts_or_prefills_secrets(account_user, monkeypatch):
    broker = BrokerAccount.objects.create(
        user=account_user,
        name="Broker",
        broker="BINANCE",
    )
    decrypt = Mock(side_effect=AssertionError("secret decrypted"))
    monkeypatch.setattr(BrokerAccount, "get_secret", decrypt)

    form = BrokerAccountForm(instance=broker)

    assert form.fields["api_key"].initial is None
    assert form.fields["api_key"].widget.render_value is False
    assert form.fields["api_secret"].initial is None
    decrypt.assert_not_called()


@pytest.mark.django_db
def test_position_api_is_read_only(client, account_user, paper_portfolio):
    client.force_login(account_user)
    response = client.post(
        reverse("api-positions-list"),
        {
            "portfolio": paper_portfolio.pk,
            "symbol": "BTCUSDT",
            "side": "LONG",
            "quantity": "1",
            "entry_price": "100",
        },
    )
    assert response.status_code == 405


@pytest.mark.django_db
def test_portfolio_api_cannot_seed_an_artificial_balance(client, account_user, paper_portfolio):
    client.force_login(account_user)
    response = client.patch(
        reverse("api-portfolios-detail", args=[paper_portfolio.pk]),
        {"starting_balance": "999999.00"},
        content_type="application/json",
    )
    assert response.status_code == 200
    paper_portfolio.refresh_from_db()
    assert paper_portfolio.starting_balance == Decimal("0.00")


@pytest.mark.django_db
def test_paper_portfolio_cannot_call_live_import(client, account_user, paper_portfolio):
    client.force_login(account_user)
    response = client.post(
        reverse("api-portfolios-import-live", args=[paper_portfolio.pk]),
    )
    assert response.status_code == 409


@pytest.mark.django_db
def test_recommendation_generation_rejects_another_users_portfolio(
    client,
    account_user,
):
    other = User.objects.create_user(
        username="other-owner",
        email="other@example.test",
        password="strong-test-password",
    )
    broker = BrokerAccount.objects.create(
        user=other,
        name="Other paper",
        broker="BINANCE",
        mode="PAPER",
    )
    portfolio = Portfolio.objects.create(
        user=other,
        broker_account=broker,
        name="Other portfolio",
    )
    client.force_login(account_user)

    response = client.post(
        reverse("api-recommendations-generate-for-portfolio"),
        {"portfolio_id": portfolio.pk},
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_trade_idea_rejects_stale_market_data(monkeypatch, account_user):
    stale = timezone.now() - timedelta(minutes=16)
    run = SimpleNamespace(id=1, payload={})
    run.save = Mock()
    row = {
        "asset": SimpleNamespace(symbol="BTCUSDT"),
        "timeframe": SimpleNamespace(code="5m", minutes=5),
        "features": {
            "close": 100,
            "atr_14": 1,
            "open_time": stale.isoformat(),
        },
        "feature_bundle": None,
        "market_snapshot": {"latest_open_time": stale.isoformat()},
    }

    monkeypatch.setattr(
        "trading.services.trade_idea_generation.MarketScannerService.scan",
        lambda **kwargs: (run, [row]),
    )
    monkeypatch.setattr(
        "trading.services.trade_idea_generation.OpportunityScoringService.score",
        lambda *args, **kwargs: {
            "overall_score": 0.9,
            "confidence_score": 0.9,
            "setup_score": 0.9,
            "risk_score": 0.8,
            "reward_score": 0.8,
            "direction": "BUY",
        },
    )
    monkeypatch.setattr(
        TradeIdeaGenerationService,
        "_get_or_create_strategy",
        lambda *args, **kwargs: SimpleNamespace(id=1),
    )

    assert TradeIdeaGenerationService.generate(user=account_user) == []


@pytest.mark.django_db
def test_ledger_replay_handles_paid_unlock(account_user):
    wallet = Wallet.objects.get(user=account_user)
    Wallet.objects.filter(pk=wallet.pk).update(
        available_balance=Decimal("0"),
        locked_balance=Decimal("0"),
    )
    WalletLedgerService.credit(
        wallet_id=wallet.pk,
        amount=Decimal("100"),
        external_event_id="test-credit",
    )
    WalletLedgerService.lock(
        wallet_id=wallet.pk,
        amount=Decimal("40"),
        external_event_id="test-lock",
    )
    WalletLedgerService.unlock(
        wallet_id=wallet.pk,
        amount=Decimal("40"),
        external_event_id="test-paid",
        to_available=False,
    )

    assert WalletLedgerService.reconstruct_balance_from_ledger(wallet.pk) == {
        "available": Decimal("60.00"),
        "locked": Decimal("0.00"),
    }


@pytest.mark.django_db
def test_wallet_stripe_session_must_match_amount_and_owner(account_user):
    from wallet.webhooks import _stripe_session_matches_transaction

    wallet = Wallet.objects.get(user=account_user)
    tx = WalletTransaction.objects.create(
        wallet=wallet,
        tx_type="DEPOSIT",
        status="PENDING",
        amount=Decimal("25.00"),
        currency="USD",
        provider="STRIPE",
        provider_session_id="cs_expected",
    )
    valid = {
        "id": "cs_expected",
        "payment_status": "paid",
        "amount_total": 2500,
        "currency": "usd",
        "client_reference_id": str(account_user.pk),
    }

    assert _stripe_session_matches_transaction(valid, tx) is True
    assert _stripe_session_matches_transaction({**valid, "amount_total": 2400}, tx) is False
    assert _stripe_session_matches_transaction(
        {**valid, "client_reference_id": "999999"},
        tx,
    ) is False


@pytest.mark.django_db
def test_quota_success_redirect_never_credits_a_pending_payment(
    client,
    account_user,
):
    quota = QuotaService.get_or_create(account_user)
    payment = AIQuotaPayment.objects.create(
        quota=quota,
        plan=AIUserQuota.PLAN_BASIC,
        amount_usd=AIUserQuota.PLAN_PRICES_USD[AIUserQuota.PLAN_BASIC],
        method=AIQuotaPayment.METHOD_STRIPE,
        status=AIQuotaPayment.STATUS_PENDING,
        stripe_session_id="cs_pending",
    )
    client.force_login(account_user)

    response = client.get(
        reverse("ai_assistant:quota_success"),
        {"session_id": "cs_pending"},
    )

    assert response.status_code == 302
    assert "quota_processing=1" in response["Location"]
    payment.refresh_from_db()
    quota.refresh_from_db()
    assert payment.status == AIQuotaPayment.STATUS_PENDING
    assert quota.plan == AIUserQuota.PLAN_FREE


@pytest.mark.django_db
def test_quota_wallet_payment_uses_the_atomic_ledger(account_user):
    wallet = Wallet.objects.get(user=account_user)
    Wallet.objects.filter(pk=wallet.pk).update(
        available_balance=Decimal("50.00"),
        locked_balance=Decimal("0.00"),
    )

    result = QuotaService.pay_with_wallet(account_user, AIUserQuota.PLAN_BASIC)

    wallet.refresh_from_db()
    assert result["ok"] is True
    assert wallet.available_balance == (
        Decimal("50.00") - AIUserQuota.PLAN_PRICES_USD[AIUserQuota.PLAN_BASIC]
    )
    payment = AIQuotaPayment.objects.get(pk=result["payment_id"])
    assert payment.status == AIQuotaPayment.STATUS_COMPLETED
    assert payment.quota.user_id == account_user.pk
    assert payment.quota.user.wallet.ledger_entries.filter(
        entry_type="DEBIT",
        transaction__tx_type="FEE",
    ).exists()


@pytest.mark.django_db
def test_public_templates_contain_no_demo_performance_values(client):
    home = client.get("/").content.decode()
    login = client.get(reverse("account_login")).content.decode()

    for fake_value in ("68.4%", "+24.8%", "87%", "3.2x", "98.2%", "49€"):
        assert fake_value not in home
    for fake_value in ("+2.34%", "+1.87%", "-0.12%"):
        assert fake_value not in login
