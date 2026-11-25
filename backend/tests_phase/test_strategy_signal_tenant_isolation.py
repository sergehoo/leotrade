from decimal import Decimal
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone


pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant_graph(user):
    from market.models import Asset, Timeframe
    from strategies.models import Signal, Strategy, StrategyRun

    other_user = get_user_model().objects.create_user(
        username="tenant-other",
        email="tenant-other@example.com",
        password="StrongPass123!",
    )
    asset = Asset.objects.create(
        name="Tenant Asset",
        symbol="TENANTUSD",
        asset_class="CRYPTO",
        exchange="TEST",
    )
    timeframe = Timeframe.objects.create(
        code="15mtenant",
        label="15 minutes tenant",
        minutes=15,
    )
    system_strategy = Strategy.objects.create(
        name="Tenant System Strategy",
        asset=asset,
        timeframe=timeframe,
    )
    own_strategy = Strategy.objects.create(
        owner=user,
        name="Tenant Private Strategy",
        asset=asset,
        timeframe=timeframe,
    )
    other_strategy = Strategy.objects.create(
        owner=other_user,
        name="Tenant Private Strategy",
        asset=asset,
        timeframe=timeframe,
    )

    def create_signal(*, strategy, signal_user=None, reason):
        return Signal.objects.create(
            strategy=strategy,
            user=signal_user,
            candle_time=timezone.now(),
            side="BUY",
            confidence=0.85,
            price=Decimal("100"),
            stop_loss=Decimal("95"),
            take_profit=Decimal("110"),
            reason=reason,
        )

    system_signal = create_signal(
        strategy=system_strategy,
        reason="global-system-signal",
    )
    own_system_signal = create_signal(
        strategy=system_strategy,
        signal_user=user,
        reason="own-system-signal",
    )
    other_system_signal = create_signal(
        strategy=system_strategy,
        signal_user=other_user,
        reason="other-system-signal",
    )
    own_private_signal = create_signal(
        strategy=own_strategy,
        reason="own-private-signal",
    )
    other_private_signal = create_signal(
        strategy=other_strategy,
        reason="other-private-signal",
    )
    own_run = StrategyRun.objects.create(strategy=own_strategy)
    other_run = StrategyRun.objects.create(strategy=other_strategy)

    return {
        "user": user,
        "other_user": other_user,
        "asset": asset,
        "system_strategy": system_strategy,
        "own_strategy": own_strategy,
        "other_strategy": other_strategy,
        "system_signal": system_signal,
        "own_system_signal": own_system_signal,
        "other_system_signal": other_system_signal,
        "own_private_signal": own_private_signal,
        "other_private_signal": other_private_signal,
        "own_run": own_run,
        "other_run": other_run,
    }


def test_model_scopes_separate_system_and_private_objects(tenant_graph):
    from strategies.models import Signal, Strategy

    user = tenant_graph["user"]
    visible_strategy_ids = set(
        Strategy.objects.visible_to(user).values_list("id", flat=True)
    )
    mutable_strategy_ids = set(
        Strategy.objects.mutable_by(user).values_list("id", flat=True)
    )
    visible_signal_ids = set(
        Signal.objects.visible_to(user).values_list("id", flat=True)
    )
    actionable_signal_ids = set(
        Signal.objects.actionable_by(user).values_list("id", flat=True)
    )

    assert visible_strategy_ids == {
        tenant_graph["system_strategy"].id,
        tenant_graph["own_strategy"].id,
    }
    assert mutable_strategy_ids == {tenant_graph["own_strategy"].id}
    assert visible_signal_ids == {
        tenant_graph["system_signal"].id,
        tenant_graph["own_system_signal"].id,
        tenant_graph["own_private_signal"].id,
    }
    assert actionable_signal_ids == {
        tenant_graph["own_system_signal"].id,
        tenant_graph["own_private_signal"].id,
    }
    assert tenant_graph["own_private_signal"].user_id == user.id


def test_strategy_signal_and_run_views_do_not_leak_other_users(client, tenant_graph):
    client.force_login(tenant_graph["user"])

    strategy_list = client.get(reverse("strategy-list"))
    signal_list = client.get(reverse("signal-list"))
    run_list = client.get(reverse("strategy-run-list"))
    strategy_api = client.get(reverse("strategy-list-api")).json()
    trading_signal_api = client.get(reverse("trading:signal-list-api")).json()

    assert {item.id for item in strategy_list.context["strategies"]} == {
        tenant_graph["system_strategy"].id,
        tenant_graph["own_strategy"].id,
    }
    assert {item.id for item in signal_list.context["signals"]} == {
        tenant_graph["system_signal"].id,
        tenant_graph["own_system_signal"].id,
        tenant_graph["own_private_signal"].id,
    }
    assert {item.id for item in run_list.context["runs"]} == {
        tenant_graph["own_run"].id,
    }
    assert {item["id"] for item in strategy_api["strategies"]} == {
        tenant_graph["system_strategy"].id,
        tenant_graph["own_strategy"].id,
    }
    assert {item["id"] for item in trading_signal_api["signals"]} == {
        tenant_graph["system_signal"].id,
        tenant_graph["own_system_signal"].id,
        tenant_graph["own_private_signal"].id,
    }

    assert client.get(
        reverse("strategy-detail", args=[tenant_graph["other_strategy"].id])
    ).status_code == 404
    assert client.get(
        reverse("signal-detail", args=[tenant_graph["other_private_signal"].id])
    ).status_code == 404
    assert client.get(
        reverse("strategy-run-detail", args=[tenant_graph["other_run"].id])
    ).status_code == 404


def test_mutations_require_ownership_and_reviews_are_audited(client, tenant_graph):
    user = tenant_graph["user"]
    own_strategy = tenant_graph["own_strategy"]
    system_strategy = tenant_graph["system_strategy"]
    other_strategy = tenant_graph["other_strategy"]
    client.force_login(user)

    client.post(reverse("strategy-toggle-active", args=[system_strategy.id]))
    client.post(reverse("strategy-toggle-active", args=[other_strategy.id]))
    client.post(reverse("strategy-toggle-active", args=[own_strategy.id]))

    system_strategy.refresh_from_db()
    other_strategy.refresh_from_db()
    own_strategy.refresh_from_db()
    assert system_strategy.is_active is True
    assert other_strategy.is_active is True
    assert own_strategy.is_active is False

    client.post(reverse("signal-approve", args=[tenant_graph["system_signal"].id]))
    client.post(reverse("signal-approve", args=[tenant_graph["other_system_signal"].id]))
    client.post(reverse("signal-approve", args=[tenant_graph["own_system_signal"].id]))

    tenant_graph["system_signal"].refresh_from_db()
    tenant_graph["other_system_signal"].refresh_from_db()
    tenant_graph["own_system_signal"].refresh_from_db()
    assert tenant_graph["system_signal"].status == "NEW"
    assert tenant_graph["other_system_signal"].status == "NEW"
    assert tenant_graph["own_system_signal"].status == "APPROVED"
    assert tenant_graph["own_system_signal"].reviewed_by_id == user.id
    assert tenant_graph["own_system_signal"].reviewed_at is not None
    assert tenant_graph["own_system_signal"].approved_at is not None


def test_backtest_launch_accepts_visible_strategy_only(client, tenant_graph):
    from leo_backtesting.models import BacktestRun

    client.force_login(tenant_graph["user"])
    with mock.patch("core.outbox._nudge_publisher"):
        system_response = client.post(
            reverse("launch-backtest", args=[tenant_graph["system_strategy"].id])
        )
        forbidden_response = client.post(
            reverse("launch-backtest", args=[tenant_graph["other_strategy"].id])
        )

    assert system_response.status_code == 302
    assert forbidden_response.status_code == 404
    assert BacktestRun.objects.filter(
        requested_by=tenant_graph["user"],
        strategy=tenant_graph["system_strategy"],
    ).count() == 1
    assert not BacktestRun.objects.filter(
        requested_by=tenant_graph["user"],
        strategy=tenant_graph["other_strategy"],
    ).exists()


def test_order_creation_rejects_foreign_signal(
    tenant_graph,
    broker_paper,
    portfolio_paper,
):
    from execution.exceptions import OrderRejected
    from execution.models import Order
    from execution.services import ExecutionOrchestrator

    with pytest.raises(OrderRejected, match="signal n'appartient"):
        ExecutionOrchestrator.create_order(
            user=tenant_graph["user"],
            portfolio=portfolio_paper,
            broker_account=broker_paper,
            symbol=tenant_graph["asset"].symbol,
            side="BUY",
            approved_quantity=Decimal("1"),
            requested_stake_amount=Decimal("100"),
            approved_notional=Decimal("100"),
            requested_price=Decimal("100"),
            signal=tenant_graph["other_system_signal"],
            asset=tenant_graph["asset"],
        )

    assert not Order.objects.exists()


def test_manual_order_api_replays_scoped_signal_error(
    client,
    tenant_graph,
    broker_paper,
    portfolio_paper,
):
    from execution.models import Order

    client.force_login(tenant_graph["user"])
    payload = {
        "portfolio_id": portfolio_paper.id,
        "broker_account_id": broker_paper.id,
        "asset_id": tenant_graph["asset"].id,
        "symbol": tenant_graph["asset"].symbol,
        "side": "BUY",
        "order_type": "MARKET",
        "approved_quantity": "1",
        "requested_stake_amount": "100",
        "approved_notional": "100",
        "requested_price": "100",
        "signal_id": tenant_graph["other_system_signal"].id,
        "source": "AI_ASSISTED",
    }
    headers = {"HTTP_X_IDEMPOTENCY_KEY": "tenant-foreign-signal"}

    first = client.post(
        reverse("api-orders-create-manual"),
        data=payload,
        content_type="application/json",
        **headers,
    )
    second = client.post(
        reverse("api-orders-create-manual"),
        data=payload,
        content_type="application/json",
        **headers,
    )

    assert first.status_code == 404
    assert second.status_code == 404
    assert first.json() == second.json() == {"detail": "Signal introuvable."}
    assert not Order.objects.exists()


def test_idempotency_keys_are_isolated_per_user(user, tenant_graph):
    from execution.idempotency import IdempotencyService

    first, first_created = IdempotencyService.get_or_create_record(
        user=user,
        endpoint="orders.create_manual",
        key="shared-client-key",
        payload={"amount": "10"},
    )
    second, second_created = IdempotencyService.get_or_create_record(
        user=tenant_graph["other_user"],
        endpoint="orders.create_manual",
        key="shared-client-key",
        payload={"amount": "25"},
    )

    assert first_created is True
    assert second_created is True
    assert first.id != second.id
