from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from market.models import Asset, Candle, Timeframe
from trading.models import MarketScanRun


class MarketScannerService:
    DEFAULT_SOURCE = "SYSTEM"
    DEFAULT_UNIVERSE = "ALL"

    @classmethod
    def _model_field_names(cls, model) -> set[str]:
        return {field.name for field in model._meta.get_fields() if hasattr(field, "name")}

    @classmethod
    def _timeframe_defaults(cls, code: str) -> dict[str, Any]:
        """
        Construit des defaults compatibles avec le vrai modèle Timeframe.
        On ne suppose plus l'existence de `name` ou `is_active`.
        """
        fields = cls._model_field_names(Timeframe)

        label_map = {
            "1m": "1 minute",
            "5m": "5 minutes",
            "15m": "15 minutes",
            "30m": "30 minutes",
            "1h": "1 heure",
            "4h": "4 heures",
            "1d": "1 jour",
        }

        defaults: dict[str, Any] = {}

        if "label" in fields:
            defaults["label"] = label_map.get(code, code.upper())
        elif "title" in fields:
            defaults["title"] = label_map.get(code, code.upper())
        elif "description" in fields:
            defaults["description"] = label_map.get(code, code.upper())

        if "minutes" in fields:
            minutes_map = {
                "1m": 1,
                "5m": 5,
                "15m": 15,
                "30m": 30,
                "1h": 60,
                "4h": 240,
                "1d": 1440,
            }
            defaults["minutes"] = minutes_map.get(code, 5)

        if "sort_order" in fields:
            sort_map = {
                "1m": 10,
                "5m": 20,
                "15m": 30,
                "30m": 40,
                "1h": 50,
                "4h": 60,
                "1d": 70,
            }
            defaults["sort_order"] = sort_map.get(code, 999)

        return defaults

    @classmethod
    def get_or_create_timeframe(cls, timeframe_code: str) -> Timeframe:
        code = (timeframe_code or "").strip()
        if not code:
            raise ValueError("timeframe_code est requis.")

        fields = cls._model_field_names(Timeframe)

        lookup = {}
        if "code" in fields:
            lookup["code"] = code
        elif "slug" in fields:
            lookup["slug"] = code
        elif "value" in fields:
            lookup["value"] = code
        else:
            raise ValueError("Le modèle Timeframe ne contient ni `code`, ni `slug`, ni `value`.")

        defaults = cls._timeframe_defaults(code)
        timeframe, _ = Timeframe.objects.get_or_create(**lookup, defaults=defaults)
        return timeframe

    @classmethod
    def _safe_timeframe_minutes(cls, timeframe: Timeframe) -> int:
        if hasattr(timeframe, "minutes") and getattr(timeframe, "minutes", None):
            try:
                return int(timeframe.minutes)
            except Exception:
                pass

        code = getattr(timeframe, "code", None) or getattr(timeframe, "slug", None) or getattr(timeframe, "value", None) or ""
        code = str(code).strip().lower()

        mapping = {
            "1m": 1,
            "5m": 5,
            "15m": 15,
            "30m": 30,
            "1h": 60,
            "4h": 240,
            "1d": 1440,
        }
        return mapping.get(code, 5)

    @classmethod
    def _safe_timeframe_code(cls, timeframe: Timeframe) -> str:
        return (
            getattr(timeframe, "code", None)
            or getattr(timeframe, "slug", None)
            or getattr(timeframe, "value", None)
            or "5m"
        )

    @classmethod
    def _build_scan_run(cls, timeframe: Timeframe, source: str, universe: str):
        """
        Crée un MarketScanRun compatible avec le vrai modèle.
        """
        fields = cls._model_field_names(MarketScanRun)
        payload = {}

        if "source" in fields:
            payload["source"] = source
        if "universe" in fields:
            payload["universe"] = universe
        if "status" in fields:
            payload["status"] = "RUNNING"
        if "started_at" in fields:
            payload["started_at"] = timezone.now()
        if "message" in fields:
            payload["message"] = "Scan marché démarré."
        if "timeframe_code" in fields:
            payload["timeframe_code"] = cls._safe_timeframe_code(timeframe)
        elif "timeframe" in fields:
            payload["timeframe"] = timeframe
        if "payload" in fields:
            payload["payload"] = {}

        return MarketScanRun.objects.create(**payload)

    @classmethod
    def _finalize_scan_run_success(cls, run, rows_count: int):
        fields = cls._model_field_names(MarketScanRun)
        update_fields = []

        if "status" in fields:
            run.status = "SUCCESS"
            update_fields.append("status")
        if "finished_at" in fields:
            run.finished_at = timezone.now()
            update_fields.append("finished_at")
        if "message" in fields:
            run.message = f"Scan terminé. {rows_count} opportunité(s) détectée(s)."
            update_fields.append("message")
        if "asset_count" in fields:
            run.asset_count = rows_count
            update_fields.append("asset_count")
        if "updated_at" in fields:
            update_fields.append("updated_at")

        if update_fields:
            run.save(update_fields=update_fields)

    @classmethod
    def _finalize_scan_run_failure(cls, run, exc: Exception):
        fields = cls._model_field_names(MarketScanRun)
        update_fields = []

        if "status" in fields:
            run.status = "FAILED"
            update_fields.append("status")
        if "finished_at" in fields:
            run.finished_at = timezone.now()
            update_fields.append("finished_at")
        if "message" in fields:
            run.message = str(exc)
            update_fields.append("message")
        if "updated_at" in fields:
            update_fields.append("updated_at")

        if update_fields:
            run.save(update_fields=update_fields)

    @classmethod
    def _extract_features(cls, candles: list[Candle]) -> dict[str, Any]:
        """
        Extraction minimale compatible avec ton scoring service.
        """
        latest = candles[0]
        previous = candles[1] if len(candles) > 1 else candles[0]

        close = float(getattr(latest, "close", 0) or 0)
        prev_close = float(getattr(previous, "close", 0) or 0)
        high = float(getattr(latest, "high", close) or close)
        low = float(getattr(latest, "low", close) or close)

        atr_14 = abs(high - low) or abs(close - prev_close) or 0.001

        sma_20 = close
        sma_50 = prev_close if prev_close > 0 else close
        rsi_14 = 60 if close >= prev_close else 40
        macd = close - sma_50
        macd_signal = 0

        return {
            "close": close,
            "previous_close": prev_close,
            "high": high,
            "low": low,
            "atr_14": atr_14,
            "sma_20": sma_20,
            "sma_50": sma_50,
            "rsi_14": rsi_14,
            "macd": macd,
            "macd_signal": macd_signal,
        }

    @classmethod
    def _build_market_snapshot(cls, asset: Asset, timeframe: Timeframe, candles: list[Candle]) -> dict[str, Any]:
        latest = candles[0]
        return {
            "asset": getattr(asset, "symbol", ""),
            "timeframe": cls._safe_timeframe_code(timeframe),
            "latest_open_time": getattr(latest, "open_time", None).isoformat() if getattr(latest, "open_time", None) else None,
            "latest_close": float(getattr(latest, "close", 0) or 0),
            "candles_used": len(candles),
        }

    @classmethod
    @transaction.atomic
    def scan(cls, timeframe_code: str = "5m", source: str | None = None, universe: str | None = None):
        source = source or cls.DEFAULT_SOURCE
        universe = universe or cls.DEFAULT_UNIVERSE

        timeframe = cls.get_or_create_timeframe(timeframe_code)
        run = cls._build_scan_run(timeframe=timeframe, source=source, universe=universe)

        rows: list[dict[str, Any]] = []

        try:
            candle_fields = cls._model_field_names(Candle)

            candle_filters = {}
            if "timeframe" in candle_fields:
                candle_filters["timeframe"] = timeframe
            elif "timeframe_code" in candle_fields:
                candle_filters["timeframe_code"] = cls._safe_timeframe_code(timeframe)

            assets = Asset.objects.filter(is_active=True).order_by("symbol")

            for asset in assets:
                candles = list(
                    Candle.objects
                    .filter(asset=asset, **candle_filters)
                    .order_by("-open_time")[:200]
                )

                if len(candles) < 20:
                    continue

                features = cls._extract_features(candles)
                market_snapshot = cls._build_market_snapshot(asset, timeframe, candles)

                rows.append({
                    "asset": asset,
                    "timeframe": timeframe,
                    "features": features,
                    "market_snapshot": market_snapshot,
                })

            cls._finalize_scan_run_success(run, len(rows))
            return run, rows

        except Exception as exc:
            cls._finalize_scan_run_failure(run, exc)
            raise