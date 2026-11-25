import math
from datetime import datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone


pytestmark = pytest.mark.django_db


def _market_and_strategy(*, suffix="default", candle_count=140):
    from market.models import Asset, Candle, Timeframe
    from strategies.models import Strategy

    asset = Asset.objects.create(
        name=f"Backtest Asset {suffix}",
        symbol=f"BT{suffix.upper()[:12]}",
        asset_class="CRYPTO",
        exchange="TEST",
    )
    timeframe = Timeframe.objects.create(
        code=f"1h{suffix[:4]}",
        label="1 hour",
        minutes=60,
    )
    strategy = Strategy.objects.create(
        name=f"SMA Backtest {suffix}",
        asset=asset,
        timeframe=timeframe,
        parameters={"backtest": {"n1": 3, "n2": 8}},
    )

    start = datetime(2024, 1, 1, tzinfo=datetime_timezone.utc)
    candles = []
    previous_close = Decimal("100")
    for index in range(candle_count):
        close = Decimal(str(100 + 12 * math.sin(index / 4) + index * 0.02))
        open_price = previous_close
        high = max(open_price, close) + Decimal("1")
        low = min(open_price, close) - Decimal("1")
        open_time = start + timedelta(hours=index)
        candles.append(
            Candle(
                asset=asset,
                timeframe=timeframe,
                open_time=open_time,
                close_time=open_time + timedelta(hours=1),
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=Decimal("1000"),
            )
        )
        previous_close = close
    Candle.objects.bulk_create(candles)
    return strategy


def _pending_run(strategy, user=None, *, suffix="run", costs=True):
    from leo_backtesting.models import BacktestRun
    from leo_backtesting.services import build_run_parameters

    return BacktestRun.objects.create(
        strategy=strategy,
        requested_by=user,
        name=f"Backtest {suffix}",
        start_date=datetime(2024, 1, 1).date(),
        end_date=datetime(2024, 1, 6).date(),
        initial_cash=Decimal("10000"),
        commission=Decimal("0.001") if costs else Decimal("0"),
        spread=Decimal("0.0002") if costs else Decimal("0"),
        slippage=Decimal("0.0001") if costs else Decimal("0"),
        parameters=build_run_parameters(strategy),
    )


def _execute(run, worker_id):
    from leo_backtesting.services import claim_backtest_run, run_backtest

    claimed = claim_backtest_run(run.id, worker_id)
    assert claimed is not None
    return run_backtest(
        claimed.strategy,
        backtest_run=claimed,
        worker_task_id=worker_id,
        raise_errors=True,
    )


def test_backtest_reuses_one_run_and_reconciles_results(client, user):
    from leo_backtesting.models import BacktestRun

    strategy = _market_and_strategy(suffix="single")
    run = _pending_run(strategy, user, suffix="single")

    completed = _execute(run, "worker-single")

    assert BacktestRun.objects.filter(strategy=strategy).count() == 1
    assert completed.status == "DONE"
    assert completed.data_points == 140
    assert len(completed.data_checksum) == 64
    assert completed.trades_log
    assert completed.parameters["execution"]["trade_on_close"] is False
    assert completed.parameters["execution"]["finalize_trades"] is True
    assert completed.metrics["trades_count"] == len(completed.trades_log)
    assert completed.metrics["final_equity"] == pytest.approx(
        completed.metrics["initial_equity"] + completed.metrics["trade_pnl_reconciled"]
    )
    assert completed.parameters["data"]["requested_end_at"]

    client.force_login(user)
    detail = client.get(reverse("backtest-detail", args=[completed.id]))
    assert detail.status_code == 200
    assert b"equity-data" in detail.content


def test_execution_costs_reduce_simulated_equity(user):
    strategy = _market_and_strategy(suffix="costs")
    without_costs = _execute(
        _pending_run(strategy, user, suffix="free", costs=False),
        "worker-free",
    )
    with_costs = _execute(
        _pending_run(strategy, user, suffix="costly", costs=True),
        "worker-costly",
    )

    assert without_costs.metrics["trades_count"] > 0
    assert with_costs.metrics["final_equity"] < without_costs.metrics["final_equity"]
    assert with_costs.metrics["total_commission"] > 0
    assert with_costs.data_checksum == without_costs.data_checksum


def test_large_trade_journal_is_bounded_without_breaking_reconciliation(user, settings):
    settings.BACKTEST_MAX_TRADE_LOG_ROWS = 3
    strategy = _market_and_strategy(suffix="bounded", candle_count=180)
    completed = _execute(
        _pending_run(strategy, user, suffix="bounded", costs=False),
        "worker-bounded",
    )

    assert completed.metrics["trades_count"] > 3
    assert completed.metrics["stored_trades_count"] == 3
    assert completed.metrics["trades_log_truncated"] is True
    assert len(completed.trades_log) == 3
    assert completed.metrics["final_equity"] == pytest.approx(
        completed.metrics["initial_equity"] + completed.metrics["trade_pnl_reconciled"]
    )


def test_only_one_worker_can_claim_a_pending_run(user):
    from leo_backtesting.services import claim_backtest_run

    strategy = _market_and_strategy(suffix="claim")
    run = _pending_run(strategy, user, suffix="claim")

    claimed = claim_backtest_run(run.id, "worker-a")
    duplicate = claim_backtest_run(run.id, "worker-b")

    assert claimed.worker_task_id == "worker-a"
    assert duplicate is None
    run.refresh_from_db()
    assert run.status == "RUNNING"
    assert run.attempt_count == 1


def test_task_marks_missing_data_failed_without_creating_duplicate(user):
    from market.models import Asset, Timeframe
    from strategies.models import Strategy
    from leo_backtesting.models import BacktestRun
    from leo_backtesting.tasks import run_backtest_task

    asset = Asset.objects.create(
        name="No data",
        symbol="NODATA",
        asset_class="FOREX",
        exchange="TEST",
    )
    timeframe = Timeframe.objects.create(code="4hnone", label="4 hours", minutes=240)
    strategy = Strategy.objects.create(
        name="No data strategy",
        asset=asset,
        timeframe=timeframe,
    )
    run = _pending_run(strategy, user, suffix="no-data")

    with mock.patch("core.realtime.RealtimeBroadcastService.broadcast_notification"):
        result = run_backtest_task(run.id)

    run.refresh_from_db()
    assert result["ok"] is False
    assert run.status == "FAILED"
    assert "closed candles are required" in run.failure_message
    assert BacktestRun.objects.filter(strategy=strategy).count() == 1


def test_inconsistent_ohlc_data_fails_closed(user):
    from market.models import Candle
    from leo_backtesting.tasks import run_backtest_task

    strategy = _market_and_strategy(suffix="invalid")
    malformed = Candle.objects.filter(asset=strategy.asset).order_by("open_time")[20]
    malformed.high = Decimal("1")
    malformed.save(update_fields=["high", "updated_at"])
    run = _pending_run(strategy, user, suffix="invalid")

    with mock.patch("core.realtime.RealtimeBroadcastService.broadcast_notification"):
        result = run_backtest_task(run.id)

    run.refresh_from_db()
    assert result["ok"] is False
    assert run.status == "FAILED"
    assert "inconsistent OHLC bounds" in run.failure_message


def test_launch_is_outbox_driven_deduplicated_and_user_scoped(client, user):
    from core.models import OutboxEvent
    from leo_backtesting.event_topics import BACKTEST_RUN_REQUESTED
    from leo_backtesting.models import BacktestRun

    strategy = _market_and_strategy(suffix="launch")
    client.force_login(user)

    with mock.patch("core.outbox._nudge_publisher"):
        first = client.post(reverse("launch-backtest", args=[strategy.id]))
        second = client.post(reverse("launch-backtest", args=[strategy.id]))

    run = BacktestRun.objects.get(requested_by=user, strategy=strategy)
    assert first.status_code == 302
    assert second.status_code == 302
    assert BacktestRun.objects.filter(requested_by=user, strategy=strategy).count() == 1
    assert OutboxEvent.objects.filter(
        topic=BACKTEST_RUN_REQUESTED,
        aggregate_id=str(run.id),
    ).count() == 1


def test_users_cannot_read_each_others_backtests(client, user):
    User = get_user_model()
    other_user = User.objects.create_user(
        username="backtest-other",
        email="backtest-other@example.com",
        password="StrongPass123!",
    )
    strategy = _market_and_strategy(suffix="private")
    own_run = _pending_run(strategy, user, suffix="own")
    other_run = _pending_run(strategy, other_user, suffix="other")
    other_run.status = "FAILED"
    other_run.save(update_fields=["status", "updated_at"])

    client.force_login(user)
    listing = client.get(reverse("backtest-list"))
    forbidden_detail = client.get(reverse("backtest-detail", args=[other_run.id]))
    forbidden_status = client.get(reverse("backtest-status", args=[other_run.id]))

    listed_ids = {item.id for item in listing.context["backtests"]}
    assert own_run.id in listed_ids
    assert other_run.id not in listed_ids
    assert forbidden_detail.status_code == 404
    assert forbidden_status.status_code == 404


def test_stale_run_is_requeued_once_through_outbox(user, settings):
    from core.models import OutboxEvent
    from leo_backtesting.models import BacktestRun
    from leo_backtesting.tasks import recover_stale_backtest_runs_task

    settings.BACKTEST_STALE_RUN_SECONDS = 60
    settings.BACKTEST_MAX_ATTEMPTS = 2
    strategy = _market_and_strategy(suffix="stale")
    run = _pending_run(strategy, user, suffix="stale")
    run.status = "RUNNING"
    run.worker_task_id = "dead-worker"
    run.started_at = timezone.now() - timedelta(minutes=5)
    run.attempt_count = 1
    run.save(
        update_fields=[
            "status",
            "worker_task_id",
            "started_at",
            "attempt_count",
            "updated_at",
        ]
    )

    with mock.patch("core.outbox._nudge_publisher"):
        result = recover_stale_backtest_runs_task()

    run.refresh_from_db()
    assert result == {"requeued": 1, "failed": 0}
    assert run.status == "PENDING"
    assert run.worker_task_id == ""
    assert OutboxEvent.objects.filter(
        idempotency_key=f"backtest:{run.id}:attempt:2"
    ).exists()
