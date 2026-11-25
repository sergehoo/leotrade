from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone


pytestmark = pytest.mark.django_db


@pytest.fixture
def live_strategy(user):
    from market.models import Asset, Timeframe
    from strategies.models import Strategy

    asset = Asset.objects.create(
        name="Deployment Asset",
        symbol="DEPLOYUSD",
        asset_class="CRYPTO",
        exchange="TEST",
    )
    timeframe = Timeframe.objects.create(
        code="5mdeploy",
        label="5 minutes deployment",
        minutes=5,
    )
    return Strategy.objects.create(
        owner=user,
        name="Deployment Strategy",
        asset=asset,
        timeframe=timeframe,
        status="PAPER",
        is_active=True,
        is_autonomous=True,
        allow_live_execution=True,
        risk_per_trade_percent=1,
    )


@pytest.fixture
def connected_live_broker(broker_live):
    broker_live.last_connection_status = True
    broker_live.last_connected_at = timezone.now()
    broker_live.save(update_fields=[
        "last_connection_status",
        "last_connected_at",
        "updated_at",
    ])
    return broker_live


def _signal(strategy, user, *, status="APPROVED"):
    from strategies.models import Signal

    return Signal.objects.create(
        strategy=strategy,
        user=user,
        candle_time=timezone.now(),
        side="BUY",
        confidence=0.9,
        price=Decimal("100"),
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        status=status,
    )


def test_live_activation_requires_verified_broker(
    user,
    live_strategy,
    portfolio_live,
):
    from strategies.services.deployment import (
        StrategyDeploymentError,
        StrategyDeploymentService,
    )

    with pytest.raises(StrategyDeploymentError, match="connexion validée"):
        StrategyDeploymentService.activate(
            strategy=live_strategy,
            user=user,
            portfolio=portfolio_live,
        )


def test_activation_is_unique_and_pauses_previous_binding(
    user,
    live_strategy,
    portfolio_paper,
    portfolio_live,
    connected_live_broker,
):
    from strategies.services.deployment import StrategyDeploymentService

    first = StrategyDeploymentService.activate(
        strategy=live_strategy,
        user=user,
        portfolio=portfolio_paper,
    )
    second = StrategyDeploymentService.activate(
        strategy=live_strategy,
        user=user,
        portfolio=portfolio_live,
        auto_execute=True,
    )

    first.refresh_from_db()
    assert first.status == "PAUSED"
    assert second.status == "ACTIVE"
    assert second.execution_mode == "LIVE"
    assert second.auto_execute is True


def test_live_status_transition_requires_active_live_deployment(
    client,
    user,
    live_strategy,
    portfolio_live,
    connected_live_broker,
):
    from strategies.services.deployment import StrategyDeploymentService

    client.force_login(user)
    client.post(
        reverse("strategy-switch-status", args=[live_strategy.id]),
        {"status": "LIVE"},
    )
    live_strategy.refresh_from_db()
    assert live_strategy.status == "PAPER"

    StrategyDeploymentService.activate(
        strategy=live_strategy,
        user=user,
        portfolio=portfolio_live,
    )
    client.post(
        reverse("strategy-switch-status", args=[live_strategy.id]),
        {"status": "LIVE"},
    )
    live_strategy.refresh_from_db()
    assert live_strategy.status == "LIVE"


def test_live_order_requires_matching_deployment_and_persists_it(
    user,
    live_strategy,
    portfolio_live,
    connected_live_broker,
):
    from execution.exceptions import OrderRejected
    from execution.services import ExecutionOrchestrator
    from strategies.services.deployment import StrategyDeploymentService

    live_strategy.status = "LIVE"
    live_strategy.save(update_fields=["status", "updated_at"])
    signal = _signal(live_strategy, user)

    with pytest.raises(OrderRejected, match="Aucun déploiement Live actif"):
        ExecutionOrchestrator.create_order(
            user=user,
            portfolio=portfolio_live,
            broker_account=connected_live_broker,
            symbol=live_strategy.asset.symbol,
            side="BUY",
            approved_quantity=Decimal("1"),
            requested_stake_amount=Decimal("100"),
            approved_notional=Decimal("100"),
            requested_price=Decimal("100"),
            signal=signal,
            asset=live_strategy.asset,
        )

    deployment = StrategyDeploymentService.activate(
        strategy=live_strategy,
        user=user,
        portfolio=portfolio_live,
    )
    order = ExecutionOrchestrator.create_order(
        user=user,
        portfolio=portfolio_live,
        broker_account=connected_live_broker,
        symbol=live_strategy.asset.symbol,
        side="BUY",
        approved_quantity=Decimal("1"),
        requested_stake_amount=Decimal("100"),
        approved_notional=Decimal("100"),
        requested_price=Decimal("100"),
        signal=signal,
        strategy_deployment=deployment,
        asset=live_strategy.asset,
    )

    assert order.strategy_deployment_id == deployment.id
    assert order.mode == "LIVE"


def test_paper_strategy_cannot_leak_to_live_broker(
    user,
    live_strategy,
    portfolio_live,
    connected_live_broker,
):
    from execution.exceptions import OrderRejected
    from execution.services import ExecutionOrchestrator

    signal = _signal(live_strategy, user)
    with pytest.raises(OrderRejected, match="n'est pas en statut Live"):
        ExecutionOrchestrator.create_order(
            user=user,
            portfolio=portfolio_live,
            broker_account=connected_live_broker,
            symbol=live_strategy.asset.symbol,
            side="BUY",
            approved_quantity=Decimal("1"),
            requested_stake_amount=Decimal("100"),
            approved_notional=Decimal("100"),
            requested_price=Decimal("100"),
            signal=signal,
            asset=live_strategy.asset,
        )


def test_auto_routing_is_explicit_and_queued_after_commit(
    django_capture_on_commit_callbacks,
    user,
    live_strategy,
    portfolio_live,
    connected_live_broker,
):
    from strategies.services.deployment import StrategyDeploymentService
    from strategies.services.execution_router import StrategyExecutionRouter

    deployment = StrategyDeploymentService.activate(
        strategy=live_strategy,
        user=user,
        portfolio=portfolio_live,
        auto_execute=True,
    )
    live_strategy.status = "LIVE"
    live_strategy.save(update_fields=["status", "updated_at"])
    signal = _signal(live_strategy, user, status="NEW")

    with mock.patch.object(StrategyExecutionRouter, "_enqueue") as enqueue:
        with django_capture_on_commit_callbacks(execute=True):
            routed, _ = StrategyExecutionRouter.route(
                signal,
                deployment=deployment,
            )

    signal.refresh_from_db()
    assert routed is True
    assert signal.status == "QUEUED"
    assert signal.model_output["strategy_deployment_id"] == deployment.id
    enqueue.assert_called_once_with(signal.id, deployment.id)


def test_paused_deployment_blocks_last_mile_broker_submission(
    user,
    live_strategy,
    portfolio_live,
    connected_live_broker,
):
    from execution.exceptions import OrderRejected
    from execution.services import ExecutionOrchestrator
    from strategies.services.deployment import StrategyDeploymentService

    deployment = StrategyDeploymentService.activate(
        strategy=live_strategy,
        user=user,
        portfolio=portfolio_live,
    )
    live_strategy.status = "LIVE"
    live_strategy.save(update_fields=["status", "updated_at"])
    signal = _signal(live_strategy, user)
    order = ExecutionOrchestrator.create_order(
        user=user,
        portfolio=portfolio_live,
        broker_account=connected_live_broker,
        symbol=live_strategy.asset.symbol,
        side="BUY",
        approved_quantity=Decimal("1"),
        requested_stake_amount=Decimal("100"),
        approved_notional=Decimal("100"),
        requested_price=Decimal("100"),
        signal=signal,
        strategy_deployment=deployment,
        asset=live_strategy.asset,
    )
    StrategyDeploymentService.pause(
        deployment_id=deployment.id,
        user=user,
    )

    with mock.patch("execution.services.BrokerAdapterFactory.build") as build:
        with pytest.raises(OrderRejected, match="n'est pas actif"):
            ExecutionOrchestrator.submit_order(order)
    build.assert_not_called()


def test_auto_execution_builds_scoped_order_intent(
    user,
    live_strategy,
    portfolio_live,
    connected_live_broker,
):
    from strategies.services.deployment import StrategyDeploymentService
    from strategies.tasks import execute_deployed_signal_task

    deployment = StrategyDeploymentService.activate(
        strategy=live_strategy,
        user=user,
        portfolio=portfolio_live,
        auto_execute=True,
    )
    live_strategy.status = "LIVE"
    live_strategy.save(update_fields=["status", "updated_at"])
    signal = _signal(live_strategy, user, status="QUEUED")

    with mock.patch(
        "execution.services.ExecutionOrchestrator.submit",
        return_value=SimpleNamespace(id=321, status="PENDING_SUBMIT"),
    ) as submit:
        result = execute_deployed_signal_task(signal.id, deployment.id)

    intent = submit.call_args.args[0]
    assert result == {"ok": True, "order_id": 321, "status": "PENDING_SUBMIT"}
    assert intent.user_id == user.id
    assert intent.portfolio_id == portfolio_live.id
    assert intent.broker_account_id == connected_live_broker.id
    assert intent.strategy_deployment_id == deployment.id
    assert intent.signal_id == signal.id
    assert intent.mode == "LIVE"


def test_user_cannot_activate_deployment_for_foreign_portfolio(
    user,
    live_strategy,
    connected_live_broker,
):
    from brokers.models import BrokerAccount
    from portfolio.models import Portfolio
    from strategies.services.deployment import (
        StrategyDeploymentError,
        StrategyDeploymentService,
    )

    other_user = get_user_model().objects.create_user(
        username="deployment-other",
        password="StrongPass123!",
    )
    other_broker = BrokerAccount.objects.create(
        user=other_user,
        broker="DERIV",
        name="Other Live",
        mode="LIVE",
        deriv_app_id="1089",
        is_active=True,
        status="ACTIVE",
        last_connection_status=True,
    )
    other_portfolio = Portfolio.objects.create(
        user=other_user,
        broker_account=other_broker,
        name="Other Portfolio",
        starting_balance=Decimal("1000"),
    )

    with pytest.raises(StrategyDeploymentError, match="n'appartient pas"):
        StrategyDeploymentService.activate(
            strategy=live_strategy,
            user=user,
            portfolio=other_portfolio,
        )
