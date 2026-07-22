from __future__ import annotations

import hashlib
import math
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation

import numpy as np
import pandas as pd
from backtesting import Backtest, Strategy as BTStrategy
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from market.models import Candle
from strategies.models import Strategy

from .models import BacktestRun


ENGINE_VERSION = "sma-cross-v2"


class BacktestError(RuntimeError):
    pass


class BacktestConfigurationError(BacktestError):
    pass


class BacktestDataError(BacktestError):
    pass


class BacktestInvariantError(BacktestError):
    pass


class BacktestRunStateError(BacktestError):
    pass


class SmaCrossStrategy(BTStrategy):
    n1 = 20
    n2 = 50
    allow_short = False

    def init(self):
        close = self.data.Close
        self.sma1 = self.I(
            lambda values: pd.Series(values).rolling(self.n1).mean(),
            close,
        )
        self.sma2 = self.I(
            lambda values: pd.Series(values).rolling(self.n2).mean(),
            close,
        )

    def next(self):
        fast_above = self.sma1[-1] > self.sma2[-1]
        fast_below = self.sma1[-1] < self.sma2[-1]

        if fast_above and not self.position.is_long:
            self.buy()
        elif self.allow_short and fast_below and not self.position.is_short:
            self.sell()
        elif not self.allow_short and fast_below and self.position.is_long:
            self.position.close()


@dataclass(frozen=True)
class BacktestConfiguration:
    n1: int
    n2: int
    allow_short: bool
    initial_cash: float
    commission: float
    spread: float
    slippage: float


@dataclass(frozen=True)
class BacktestResult:
    start_date: object
    end_date: object
    parameters: dict
    metrics: dict
    equity_curve: list
    trades_log: list
    data_points: int
    data_checksum: str


def execution_assumptions_for(strategy: Strategy) -> dict:
    costs = getattr(settings, "BACKTEST_EXECUTION_COSTS", {}) or {}
    asset_class = getattr(strategy.asset, "asset_class", "DEFAULT") or "DEFAULT"
    selected = costs.get(asset_class, costs.get("DEFAULT", {}))
    return {
        "initial_cash": _decimal_setting("BACKTEST_DEFAULT_INITIAL_CASH", "10000"),
        "commission": _to_decimal(selected.get("commission", "0.001"), "commission"),
        "spread": _to_decimal(selected.get("spread", "0"), "spread"),
        "slippage": _to_decimal(selected.get("slippage", "0"), "slippage"),
    }


def build_run_parameters(strategy: Strategy) -> dict:
    source = deepcopy(strategy.parameters or {})
    strategy_source = source.get("backtest", source)
    if not isinstance(strategy_source, dict):
        strategy_source = {}

    return {
        "engine": {
            "name": "SMA_CROSS",
            "version": ENGINE_VERSION,
        },
        "strategy": {
            "n1": strategy_source.get("n1", 20),
            "n2": strategy_source.get("n2", 50),
            "allow_short": strategy_source.get("allow_short", False),
        },
        "strategy_snapshot": {
            "id": strategy.id,
            "name": strategy.name,
            "updated_at": strategy.updated_at.isoformat() if strategy.updated_at else None,
            "parameters": source,
            "entry_rules": deepcopy(strategy.entry_rules or {}),
            "exit_rules": deepcopy(strategy.exit_rules or {}),
        },
        "data": {
            "requested_end_at": timezone.now().isoformat(),
        },
    }


def claim_backtest_run(backtest_run_id: int, worker_task_id: str) -> BacktestRun | None:
    with transaction.atomic():
        run = (
            BacktestRun.objects.select_for_update()
            .select_related("strategy", "strategy__asset", "strategy__timeframe")
            .filter(pk=backtest_run_id)
            .first()
        )
        if run is None or run.status != "PENDING":
            return None

        run.status = "RUNNING"
        run.worker_task_id = worker_task_id
        run.started_at = timezone.now()
        run.completed_at = None
        run.failure_message = ""
        run.attempt_count += 1
        run.save(
            update_fields=[
                "status",
                "worker_task_id",
                "started_at",
                "completed_at",
                "failure_message",
                "attempt_count",
                "updated_at",
            ]
        )
        return run


def mark_backtest_failed(
    backtest_run_id: int,
    exc: Exception | str,
    *,
    worker_task_id: str = "",
) -> BacktestRun | None:
    message = _failure_message(exc)
    with transaction.atomic():
        run = BacktestRun.objects.select_for_update().filter(pk=backtest_run_id).first()
        if run is None or run.status in ("DONE", "FAILED"):
            return run
        if worker_task_id and run.worker_task_id != worker_task_id:
            return run

        run.status = "FAILED"
        run.failure_message = message
        run.metrics = {"error": message}
        run.completed_at = timezone.now()
        run.save(
            update_fields=[
                "status",
                "failure_message",
                "metrics",
                "completed_at",
                "updated_at",
            ]
        )
        return run


def run_backtest(
    strategy: Strategy,
    *,
    backtest_run: BacktestRun | None = None,
    worker_task_id: str = "",
    raise_errors: bool = False,
) -> BacktestRun:
    run = backtest_run
    if run is None:
        assumptions = execution_assumptions_for(strategy)
        worker_task_id = worker_task_id or f"sync-{uuid.uuid4()}"
        today = timezone.localdate()
        run = BacktestRun.objects.create(
            strategy=strategy,
            name=f"BT - {strategy.name}",
            start_date=today,
            end_date=today,
            initial_cash=assumptions["initial_cash"],
            commission=assumptions["commission"],
            spread=assumptions["spread"],
            slippage=assumptions["slippage"],
            parameters=build_run_parameters(strategy),
            status="RUNNING",
            engine_version=ENGINE_VERSION,
            worker_task_id=worker_task_id,
            started_at=timezone.now(),
            attempt_count=1,
        )

    worker_task_id = worker_task_id or run.worker_task_id
    try:
        result = _execute_backtest(run)
        _persist_result(run.id, worker_task_id, result)
    except Exception as exc:
        mark_backtest_failed(run.id, exc, worker_task_id=worker_task_id)
        if raise_errors:
            raise

    return BacktestRun.objects.get(pk=run.id)


def _execute_backtest(run: BacktestRun) -> BacktestResult:
    if run.status != "RUNNING":
        raise BacktestRunStateError(f"Backtest run {run.id} is not RUNNING")

    config = _configuration_from_run(run)
    dataframe, rows, data_quality = _load_and_validate_candles(run, config)

    engine = Backtest(
        dataframe,
        SmaCrossStrategy,
        cash=config.initial_cash,
        commission=config.commission,
        spread=config.spread + config.slippage,
        trade_on_close=False,
        hedging=False,
        exclusive_orders=True,
        finalize_trades=True,
    )
    stats = engine.run(
        n1=config.n1,
        n2=config.n2,
        allow_short=config.allow_short,
    )

    equity_curve = _serialize_equity_curve(stats["_equity_curve"])
    trades_log, trades_log_truncated = _serialize_trades(stats["_trades"])
    gross_trade_pnl = (
        _finite_number(stats["_trades"]["PnL"].sum()) if len(stats["_trades"]) else 0.0
    )
    if gross_trade_pnl is None:
        raise BacktestInvariantError("Trade ledger contains a non-finite PnL")
    metrics = _normalize_metrics(
        stats,
        config,
        equity_curve,
        gross_trade_pnl,
        len(trades_log),
        trades_log_truncated,
        data_quality,
    )
    checksum = _checksum(rows)

    parameters = deepcopy(run.parameters or {})
    parameters["engine"] = {
        "name": "SMA_CROSS",
        "version": ENGINE_VERSION,
    }
    parameters["strategy"] = {
        "n1": config.n1,
        "n2": config.n2,
        "allow_short": config.allow_short,
    }
    parameters["execution"] = {
        "initial_cash": config.initial_cash,
        "commission_rate": config.commission,
        "spread_rate": config.spread,
        "slippage_rate": config.slippage,
        "effective_spread_rate": config.spread + config.slippage,
        "slippage_model": "added_to_bid_ask_spread",
        "trade_on_close": False,
        "exclusive_orders": True,
        "finalize_trades": True,
    }
    requested_data = parameters.get("data", {})
    if not isinstance(requested_data, dict):
        requested_data = {}
    parameters["data"] = {
        **requested_data,
        "asset_id": run.strategy.asset_id,
        "asset": run.strategy.asset.symbol,
        "timeframe": run.strategy.timeframe.code,
        "start_at": dataframe.index.min().isoformat(),
        "end_at": dataframe.index.max().isoformat(),
        "candle_count": len(dataframe),
        "checksum_sha256": checksum,
        **data_quality,
    }

    return BacktestResult(
        start_date=dataframe.index.min().date(),
        end_date=dataframe.index.max().date(),
        parameters=parameters,
        metrics=metrics,
        equity_curve=equity_curve,
        trades_log=trades_log,
        data_points=len(dataframe),
        data_checksum=checksum,
    )


def _persist_result(run_id: int, worker_task_id: str, result: BacktestResult) -> None:
    now = timezone.now()
    filters = {
        "pk": run_id,
        "status": "RUNNING",
    }
    if worker_task_id:
        filters["worker_task_id"] = worker_task_id

    updated = BacktestRun.objects.filter(**filters).update(
        start_date=result.start_date,
        end_date=result.end_date,
        parameters=result.parameters,
        metrics=result.metrics,
        equity_curve=result.equity_curve,
        trades_log=result.trades_log,
        data_points=result.data_points,
        data_checksum=result.data_checksum,
        engine_version=ENGINE_VERSION,
        failure_message="",
        status="DONE",
        completed_at=now,
        updated_at=now,
    )
    if updated != 1:
        raise BacktestRunStateError(f"Backtest run {run_id} lost its execution lease")


def _configuration_from_run(run: BacktestRun) -> BacktestConfiguration:
    parameters = run.parameters if isinstance(run.parameters, dict) else {}
    strategy_parameters = parameters.get("strategy", parameters)
    if not isinstance(strategy_parameters, dict):
        strategy_parameters = {}

    n1 = _positive_int(strategy_parameters.get("n1", 20), "n1")
    n2 = _positive_int(strategy_parameters.get("n2", 50), "n2")
    if n1 >= n2:
        raise BacktestConfigurationError("n1 must be strictly lower than n2")
    if n2 > 5000:
        raise BacktestConfigurationError("n2 exceeds the supported maximum of 5000")

    initial_cash = _bounded_float(run.initial_cash, "initial_cash", 0.01, 1e18)
    commission = _bounded_float(run.commission, "commission", 0, 0.10)
    spread = _bounded_float(run.spread, "spread", 0, 0.05)
    slippage = _bounded_float(run.slippage, "slippage", 0, 0.05)

    return BacktestConfiguration(
        n1=n1,
        n2=n2,
        allow_short=_to_bool(strategy_parameters.get("allow_short", False)),
        initial_cash=initial_cash,
        commission=commission,
        spread=spread,
        slippage=slippage,
    )


def _load_and_validate_candles(
    run: BacktestRun,
    config: BacktestConfiguration,
) -> tuple[pd.DataFrame, list[dict], dict]:
    queryset = Candle.objects.filter(
        asset=run.strategy.asset,
        timeframe=run.strategy.timeframe,
        close_time__lte=timezone.now(),
    )
    queryset = _apply_requested_date_range(queryset, run.parameters or {})
    queryset = queryset.order_by("open_time")

    max_candles = int(getattr(settings, "BACKTEST_MAX_CANDLES", 200_000))
    candle_count = queryset.count()
    if candle_count > max_candles:
        raise BacktestDataError(
            f"Dataset contains {candle_count} candles; limit is {max_candles}. "
            "Specify a narrower date range."
        )

    rows = list(
        queryset.values(
            "open_time",
            "close_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
        )
    )
    minimum = config.n2 + 2
    if len(rows) < minimum:
        raise BacktestDataError(
            f"At least {minimum} closed candles are required; found {len(rows)}"
        )

    gap_count = 0
    missing_intervals = 0
    expected_seconds = max(1, int(run.strategy.timeframe.minutes) * 60)
    previous_open = None

    for row in rows:
        _validate_ohlcv_row(row)
        current_open = row["open_time"]
        if previous_open is not None:
            elapsed = (current_open - previous_open).total_seconds()
            if elapsed <= 0:
                raise BacktestDataError("Candle timestamps must be strictly increasing")
            if elapsed > expected_seconds * 1.5:
                gap_count += 1
                missing_intervals += max(1, round(elapsed / expected_seconds) - 1)
        previous_open = current_open

    dataframe = pd.DataFrame(rows)
    dataframe.rename(
        columns={
            "open_time": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        },
        inplace=True,
    )
    dataframe.drop(columns=["close_time"], inplace=True)
    for column in ("Open", "High", "Low", "Close", "Volume"):
        dataframe[column] = pd.to_numeric(dataframe[column], errors="raise").astype(float)
    dataframe["Date"] = pd.to_datetime(dataframe["Date"], utc=True)
    dataframe.set_index("Date", inplace=True)

    return dataframe, rows, {
        "gap_count": gap_count,
        "estimated_missing_candles": missing_intervals,
    }


def _apply_requested_date_range(queryset, parameters: dict):
    data_parameters = parameters.get("data", {}) if isinstance(parameters, dict) else {}
    if not isinstance(data_parameters, dict):
        return queryset

    requested_start = data_parameters.get("requested_start_at")
    requested_end = data_parameters.get("requested_end_at")
    if requested_start:
        queryset = queryset.filter(open_time__gte=_parse_boundary(requested_start, end=False))
    if requested_end:
        end_value, inclusive = _parse_end_boundary(requested_end)
        lookup = "open_time__lte" if inclusive else "open_time__lt"
        queryset = queryset.filter(**{lookup: end_value})
    return queryset


def _parse_boundary(value, *, end: bool):
    text = str(value).strip()
    parsed_datetime = parse_datetime(text.replace("Z", "+00:00"))
    if parsed_datetime is not None:
        if timezone.is_naive(parsed_datetime):
            parsed_datetime = timezone.make_aware(parsed_datetime, timezone.get_current_timezone())
        return parsed_datetime

    parsed_date = parse_date(text)
    if parsed_date is None:
        raise BacktestConfigurationError(f"Invalid data boundary: {text}")
    boundary = datetime.combine(parsed_date, time.max if end else time.min)
    return timezone.make_aware(boundary, timezone.get_current_timezone())


def _parse_end_boundary(value):
    text = str(value).strip()
    if parse_datetime(text.replace("Z", "+00:00")) is not None:
        return _parse_boundary(text, end=True), True
    parsed_date = parse_date(text)
    if parsed_date is None:
        raise BacktestConfigurationError(f"Invalid data boundary: {text}")
    next_day = datetime.combine(parsed_date + timedelta(days=1), time.min)
    return timezone.make_aware(next_day, timezone.get_current_timezone()), False


def _validate_ohlcv_row(row: dict) -> None:
    timestamp = row["open_time"].isoformat()
    try:
        open_price = _finite_decimal(row["open"])
        high_price = _finite_decimal(row["high"])
        low_price = _finite_decimal(row["low"])
        close_price = _finite_decimal(row["close"])
        volume = _finite_decimal(row["volume"])
    except BacktestDataError as exc:
        raise BacktestDataError(f"Invalid candle at {timestamp}: {exc}") from exc

    if min(open_price, high_price, low_price, close_price) <= 0:
        raise BacktestDataError(f"Invalid candle at {timestamp}: OHLC prices must be positive")
    if high_price < max(open_price, close_price) or low_price > min(open_price, close_price):
        raise BacktestDataError(f"Invalid candle at {timestamp}: inconsistent OHLC bounds")
    if high_price < low_price:
        raise BacktestDataError(f"Invalid candle at {timestamp}: high is below low")
    if volume < 0:
        raise BacktestDataError(f"Invalid candle at {timestamp}: volume is negative")


def _normalize_metrics(
    stats,
    config: BacktestConfiguration,
    equity_curve: list,
    gross_trade_pnl: float,
    stored_trades_count: int,
    trades_log_truncated: bool,
    data_quality: dict,
) -> dict:
    initial_equity = config.initial_cash
    final_equity = _finite_number(stats.get("Equity Final [$]"))
    equity_peak = _finite_number(stats.get("Equity Peak [$]"))
    total_commission = _finite_number(stats.get("Commissions [$]")) or 0.0
    net_trade_pnl = gross_trade_pnl - total_commission
    expected_final = initial_equity + net_trade_pnl
    tolerance = max(0.01, initial_equity * 1e-8)

    if final_equity is None:
        raise BacktestInvariantError("Engine did not produce a finite final equity")
    if abs(final_equity - expected_final) > tolerance:
        raise BacktestInvariantError("Final equity does not reconcile with the trade ledger")
    if equity_curve and abs(float(equity_curve[-1]["equity"]) - final_equity) > tolerance:
        raise BacktestInvariantError("Final equity does not reconcile with the equity curve")

    calculated_return = (final_equity / initial_equity - 1) * 100
    reported_return = _finite_number(stats.get("Return [%]"))
    if reported_return is not None and abs(calculated_return - reported_return) > 1e-6:
        raise BacktestInvariantError("Reported return does not reconcile with final equity")

    return {
        "initial_equity": initial_equity,
        "final_equity": final_equity,
        "equity_peak": equity_peak,
        "net_profit": final_equity - initial_equity,
        "return_pct": calculated_return,
        "buy_hold_return_pct": _finite_number(stats.get("Buy & Hold Return [%]")),
        "annualized_return_pct": _finite_number(stats.get("Return (Ann.) [%]")),
        "cagr_pct": _finite_number(stats.get("CAGR [%]")),
        "annualized_volatility_pct": _finite_number(stats.get("Volatility (Ann.) [%]")),
        "max_drawdown_pct": _absolute_number(stats.get("Max. Drawdown [%]")),
        "avg_drawdown_pct": _absolute_number(stats.get("Avg. Drawdown [%]")),
        "exposure_time_pct": _finite_number(stats.get("Exposure Time [%]")),
        "sharpe_ratio": _finite_number(stats.get("Sharpe Ratio")),
        "sortino_ratio": _finite_number(stats.get("Sortino Ratio")),
        "calmar_ratio": _finite_number(stats.get("Calmar Ratio")),
        "profit_factor": _finite_number(stats.get("Profit Factor")),
        "expectancy_pct": _finite_number(stats.get("Expectancy [%]")),
        "sqn": _finite_number(stats.get("SQN")),
        "trades_count": int(stats.get("# Trades", 0) or 0),
        "stored_trades_count": stored_trades_count,
        "trades_log_truncated": trades_log_truncated,
        "win_rate_pct": _finite_number(stats.get("Win Rate [%]")),
        "best_trade_pct": _finite_number(stats.get("Best Trade [%]")),
        "worst_trade_pct": _finite_number(stats.get("Worst Trade [%]")),
        "avg_trade_pct": _finite_number(stats.get("Avg. Trade [%]")),
        "total_commission": total_commission,
        "gross_trade_pnl": gross_trade_pnl,
        "trade_pnl_reconciled": net_trade_pnl,
        "data_quality": data_quality,
        "execution_assumptions": {
            "commission_rate": config.commission,
            "spread_rate": config.spread,
            "slippage_rate": config.slippage,
        },
    }


def _serialize_equity_curve(dataframe: pd.DataFrame) -> list[dict]:
    max_points = max(2, int(getattr(settings, "BACKTEST_MAX_EQUITY_POINTS", 5000)))
    row_count = len(dataframe)
    step = max(1, math.ceil(row_count / max_points))
    selected = list(range(0, row_count, step))
    if row_count and selected[-1] != row_count - 1:
        selected.append(row_count - 1)

    curve = []
    for position in selected:
        timestamp = dataframe.index[position]
        row = dataframe.iloc[position]
        curve.append(
            {
                "timestamp": _json_value(timestamp),
                "equity": _finite_number(row.get("Equity")) or 0.0,
                "drawdown_pct": (_finite_number(row.get("DrawdownPct")) or 0.0) * 100,
                "drawdown_duration_seconds": _duration_seconds(row.get("DrawdownDuration")),
            }
        )
    return curve


def _serialize_trades(dataframe: pd.DataFrame) -> tuple[list[dict], bool]:
    total_rows = len(dataframe)
    max_rows = max(1, int(getattr(settings, "BACKTEST_MAX_TRADE_LOG_ROWS", 10_000)))
    truncated = total_rows > max_rows
    if truncated:
        first_count = math.ceil(max_rows / 2)
        last_count = max_rows - first_count
        selected_positions = list(range(first_count))
        if last_count:
            selected_positions.extend(range(total_rows - last_count, total_rows))
    else:
        selected_positions = list(range(total_rows))

    records = []
    for position in selected_positions:
        row = dataframe.iloc[position]
        records.append(
            {
                "trade_number": position + 1,
                "size": _finite_number(row.get("Size")),
                "entry_bar": _integer_or_none(row.get("EntryBar")),
                "exit_bar": _integer_or_none(row.get("ExitBar")),
                "entry_time": _json_value(row.get("EntryTime")),
                "exit_time": _json_value(row.get("ExitTime")),
                "entry_price": _finite_number(row.get("EntryPrice")),
                "exit_price": _finite_number(row.get("ExitPrice")),
                "stop_loss": _finite_number(row.get("SL")),
                "take_profit": _finite_number(row.get("TP")),
                "pnl": _finite_number(row.get("PnL")) or 0.0,
                "return_pct": (_finite_number(row.get("ReturnPct")) or 0.0) * 100,
                "duration_seconds": _duration_seconds(row.get("Duration")),
                "tag": _json_value(row.get("Tag")),
            }
        )
    return records, truncated


def _checksum(rows: list[dict]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(
            "|".join(
                str(row[key])
                for key in (
                    "open_time",
                    "close_time",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                )
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _finite_decimal(value) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise BacktestDataError("value is not numeric") from exc
    if not result.is_finite():
        raise BacktestDataError("value is not finite")
    return result


def _to_decimal(value, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise BacktestConfigurationError(f"{field_name} must be numeric") from exc
    if not result.is_finite():
        raise BacktestConfigurationError(f"{field_name} must be finite")
    return result


def _decimal_setting(name: str, default: str) -> Decimal:
    return _to_decimal(getattr(settings, name, default), name)


def _bounded_float(value, field_name: str, minimum: float, maximum: float) -> float:
    result = float(_to_decimal(value, field_name))
    if not minimum <= result <= maximum:
        raise BacktestConfigurationError(
            f"{field_name} must be between {minimum} and {maximum}"
        )
    return result


def _positive_int(value, field_name: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise BacktestConfigurationError(f"{field_name} must be an integer") from exc
    if result <= 0:
        raise BacktestConfigurationError(f"{field_name} must be positive")
    return result


def _to_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _finite_number(value) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _absolute_number(value) -> float | None:
    result = _finite_number(value)
    return abs(result) if result is not None else None


def _integer_or_none(value) -> int | None:
    result = _finite_number(value)
    return int(result) if result is not None else None


def _duration_seconds(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (pd.Timedelta, timedelta)):
        return value.total_seconds()
    return None


def _json_value(value):
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, (pd.Timedelta, timedelta)):
        return value.total_seconds()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (str, int, bool)):
        return value
    return str(value)


def _failure_message(exc: Exception | str) -> str:
    if isinstance(exc, str):
        return exc[:1000]
    return f"{type(exc).__name__}: {exc}"[:1000]
