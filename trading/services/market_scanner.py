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
        Extraction d'indicateurs techniques réels via la bibliothèque `ta`.
        Nécessite au moins 26 chandeliers pour MACD, 14 pour RSI/ATR.
        Les candles sont triées du plus ancien [−1] au plus récent [0].
        """
        import numpy as np

        # Trier du plus ancien au plus récent (candles[0] = le plus récent)
        ordered = list(reversed(candles))

        def _f(c, attr, fallback=0.0) -> float:
            return float(getattr(c, attr, fallback) or fallback)

        closes = np.array([_f(c, "close") for c in ordered], dtype=float)
        highs  = np.array([_f(c, "high",  closes[i]) for i, c in enumerate(ordered)], dtype=float)
        lows   = np.array([_f(c, "low",   closes[i]) for i, c in enumerate(ordered)], dtype=float)

        n = len(closes)
        close = float(closes[-1])
        prev_close = float(closes[-2]) if n >= 2 else close
        high = float(highs[-1])
        low  = float(lows[-1])

        # ── SMA ──────────────────────────────────────────────────────────────
        sma_20 = float(np.mean(closes[-20:])) if n >= 20 else close
        sma_50 = float(np.mean(closes[-50:])) if n >= 50 else sma_20

        # ── ATR (14) ─────────────────────────────────────────────────────────
        if n >= 2:
            trs = np.maximum.reduce([
                highs[1:] - lows[1:],
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:]  - closes[:-1]),
            ])
            atr_14 = float(np.mean(trs[-14:])) if len(trs) >= 14 else float(np.mean(trs))
        else:
            atr_14 = abs(high - low) or 0.001
        atr_14 = atr_14 or 0.001

        # ── RSI (14) ─────────────────────────────────────────────────────────
        rsi_14 = 50.0
        if n >= 15:
            deltas = np.diff(closes)
            gains  = np.where(deltas > 0, deltas, 0.0)
            losses = np.where(deltas < 0, -deltas, 0.0)
            avg_gain = float(np.mean(gains[-14:]))
            avg_loss = float(np.mean(losses[-14:]))
            if avg_loss == 0:
                rsi_14 = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi_14 = 100.0 - (100.0 / (1.0 + rs))

        # ── MACD (12, 26, 9) ─────────────────────────────────────────────────
        macd_line = 0.0
        macd_signal = 0.0
        if n >= 26:
            def _ema(arr: np.ndarray, period: int) -> np.ndarray:
                k = 2.0 / (period + 1)
                ema = np.empty_like(arr)
                ema[0] = arr[0]
                for i in range(1, len(arr)):
                    ema[i] = arr[i] * k + ema[i - 1] * (1 - k)
                return ema

            ema12 = _ema(closes, 12)
            ema26 = _ema(closes, 26)
            macd_arr = ema12 - ema26
            signal_arr = _ema(macd_arr, 9)
            macd_line   = float(macd_arr[-1])
            macd_signal = float(signal_arr[-1])

        # ── Bollinger Bands (20, 2σ) ──────────────────────────────────────────
        bb_high = bb_low = 0.0
        if n >= 20:
            window = closes[-20:]
            std = float(np.std(window))
            bb_high = sma_20 + 2 * std
            bb_low  = sma_20 - 2 * std

        # ── Returns ───────────────────────────────────────────────────────────
        returns_1 = (close - prev_close) / prev_close if prev_close else 0.0
        returns_5 = (close - float(closes[-6])) / float(closes[-6]) if n >= 6 else returns_1
        volatility_20 = float(np.std(np.diff(closes[-21:]) / closes[-21:-1])) if n >= 21 else 0.0

        return {
            "close":        close,
            "previous_close": prev_close,
            "high":         high,
            "low":          low,
            "atr_14":       round(atr_14, 6),
            "sma_20":       round(sma_20, 6),
            "sma_50":       round(sma_50, 6),
            "rsi_14":       round(rsi_14, 2),
            "macd":         round(macd_line, 6),
            "macd_signal":  round(macd_signal, 6),
            "bb_high":      round(bb_high, 6),
            "bb_low":       round(bb_low, 6),
            "returns_1":    round(returns_1, 6),
            "returns_5":    round(returns_5, 6),
            "volatility_20": round(volatility_20, 6),
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

                # Minimum 27 chandeliers requis : 26 pour MACD + 1 de marge
                # RSI besoin de 15, ATR de 14 — on retient 27 comme plancher
                if len(candles) < 27:
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