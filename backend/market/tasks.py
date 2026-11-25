# market/tasks.py
from __future__ import annotations

import logging

from celery import shared_task

from market.models import Asset, Timeframe
from market.servicess.candle_importers.binance import BinanceCandleImporter
from market.servicess.candle_importers.deriv import DerivCandleImporter
from market.servicess.features import FeatureComputationService


logger = logging.getLogger(__name__)


SHORT_TIMEFRAMES = ["5m", "15m", "1h"]
LONG_TIMEFRAMES = ["4h", "1d", "1w", "1M"]
ALL_TIMEFRAMES = SHORT_TIMEFRAMES + LONG_TIMEFRAMES


def _empty_summary(task_name: str, exchange: str | None = None, scope: str | None = None) -> dict:
    return {
        "task": task_name,
        "exchange": exchange,
        "scope": scope,
        "ok": 0,
        "skipped": 0,
        "failed": 0,
        "results": [],
    }


def _append_result(summary: dict, result: dict) -> None:
    summary["results"].append(result)

    status = result.get("status", "ok")
    if status == "ok":
        summary["ok"] += 1
    elif status == "skipped":
        summary["skipped"] += 1
    else:
        summary["failed"] += 1


def _wrap_failure_result(asset, timeframe, exc: Exception, *, source: str) -> dict:
    logger.exception(
        "%s failed for asset=%s timeframe=%s",
        source,
        getattr(asset, "symbol", None),
        getattr(timeframe, "code", None),
    )
    return {
        "status": "failed",
        "reason": str(exc),
        "asset": getattr(asset, "symbol", None),
        "timeframe": getattr(timeframe, "code", None),
        "source": source,
    }


@shared_task
def sync_binance_klines():
    summary = _empty_summary("sync_binance_klines", exchange="BINANCE", scope="short")

    assets = Asset.objects.filter(exchange="BINANCE", is_active=True).order_by("symbol")
    timeframes = Timeframe.objects.filter(code__in=SHORT_TIMEFRAMES).order_by("minutes")

    for asset in assets:
        for timeframe in timeframes:
            try:
                result = BinanceCandleImporter.import_klines(
                    asset=asset,
                    timeframe=timeframe,
                    limit=500,
                )

                if not isinstance(result, dict):
                    result = {
                        "status": "ok",
                        "asset": asset.symbol,
                        "timeframe": timeframe.code,
                        "data": result,
                    }

                _append_result(summary, result)

            except Exception as exc:
                _append_result(
                    summary,
                    _wrap_failure_result(asset, timeframe, exc, source="BinanceCandleImporter.import_klines"),
                )

    return summary


@shared_task
def sync_binance_long_klines():
    summary = _empty_summary("sync_binance_long_klines", exchange="BINANCE", scope="long")

    assets = Asset.objects.filter(exchange="BINANCE", is_active=True).order_by("symbol")
    timeframes = Timeframe.objects.filter(code__in=LONG_TIMEFRAMES).order_by("minutes")

    for asset in assets:
        for timeframe in timeframes:
            try:
                result = BinanceCandleImporter.import_klines(
                    asset=asset,
                    timeframe=timeframe,
                    limit=300,
                )

                if not isinstance(result, dict):
                    result = {
                        "status": "ok",
                        "asset": asset.symbol,
                        "timeframe": timeframe.code,
                        "data": result,
                    }

                _append_result(summary, result)

            except Exception as exc:
                _append_result(
                    summary,
                    _wrap_failure_result(asset, timeframe, exc, source="BinanceCandleImporter.import_klines"),
                )

    return summary


@shared_task
def sync_deriv_candles():
    summary = _empty_summary("sync_deriv_candles", exchange="DERIV", scope="short")

    assets = Asset.objects.filter(exchange="DERIV", is_active=True).order_by("symbol")
    timeframes = Timeframe.objects.filter(code__in=SHORT_TIMEFRAMES).order_by("minutes")

    for asset in assets:
        for timeframe in timeframes:
            try:
                result = DerivCandleImporter.import_candles(
                    asset=asset,
                    timeframe=timeframe,
                    count=300,
                )

                if not isinstance(result, dict):
                    result = {
                        "status": "ok",
                        "asset": asset.symbol,
                        "timeframe": timeframe.code,
                        "data": result,
                    }

                _append_result(summary, result)

            except Exception as exc:
                _append_result(
                    summary,
                    _wrap_failure_result(asset, timeframe, exc, source="DerivCandleImporter.import_candles"),
                )

    return summary


@shared_task
def sync_deriv_long_candles():
    summary = _empty_summary("sync_deriv_long_candles", exchange="DERIV", scope="long")

    assets = Asset.objects.filter(exchange="DERIV", is_active=True).order_by("symbol")
    timeframes = Timeframe.objects.filter(code__in=["4h", "1d", "1w"]).order_by("minutes")

    for asset in assets:
        for timeframe in timeframes:
            try:
                result = DerivCandleImporter.import_candles(
                    asset=asset,
                    timeframe=timeframe,
                    count=200,
                )

                if not isinstance(result, dict):
                    result = {
                        "status": "ok",
                        "asset": asset.symbol,
                        "timeframe": timeframe.code,
                        "data": result,
                    }

                _append_result(summary, result)

            except Exception as exc:
                _append_result(
                    summary,
                    _wrap_failure_result(asset, timeframe, exc, source="DerivCandleImporter.import_candles"),
                )

    return summary


@shared_task
def compute_market_features_task():
    summary = _empty_summary("compute_market_features_task", exchange="ALL", scope="short")

    assets = Asset.objects.filter(is_active=True).order_by("symbol")
    timeframes = Timeframe.objects.filter(code__in=SHORT_TIMEFRAMES).order_by("minutes")

    for asset in assets:
        for timeframe in timeframes:
            try:
                result = FeatureComputationService.compute_for_asset_timeframe(
                    asset=asset,
                    timeframe=timeframe,
                    lookback=500,
                )

                if not isinstance(result, dict):
                    result = {
                        "status": "ok",
                        "asset": asset.symbol,
                        "timeframe": timeframe.code,
                        "data": result,
                    }

                result.setdefault("status", "ok")
                result.setdefault("asset", asset.symbol)
                result.setdefault("timeframe", timeframe.code)

                _append_result(summary, result)

            except Exception as exc:
                _append_result(
                    summary,
                    _wrap_failure_result(asset, timeframe, exc, source="FeatureComputationService.compute_for_asset_timeframe"),
                )

    return summary


@shared_task
def compute_market_features_long_task():
    summary = _empty_summary("compute_market_features_long_task", exchange="ALL", scope="long")

    assets = Asset.objects.filter(is_active=True).order_by("symbol")
    timeframes = Timeframe.objects.filter(code__in=LONG_TIMEFRAMES).order_by("minutes")

    for asset in assets:
        for timeframe in timeframes:
            try:
                result = FeatureComputationService.compute_for_asset_timeframe(
                    asset=asset,
                    timeframe=timeframe,
                    lookback=300,
                )

                if not isinstance(result, dict):
                    result = {
                        "status": "ok",
                        "asset": asset.symbol,
                        "timeframe": timeframe.code,
                        "data": result,
                    }

                result.setdefault("status", "ok")
                result.setdefault("asset", asset.symbol)
                result.setdefault("timeframe", timeframe.code)

                _append_result(summary, result)

            except Exception as exc:
                _append_result(
                    summary,
                    _wrap_failure_result(asset, timeframe, exc, source="FeatureComputationService.compute_for_asset_timeframe"),
                )

    return summary