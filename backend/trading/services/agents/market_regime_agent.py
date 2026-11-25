from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction
from django.utils import timezone

from market.models import Timeframe
from trading.models import AgentRun, MarketRegimeSnapshot


class MarketRegimeAgent:
    """
    Détermine le régime de marché à partir des opportunités/scans récents.
    Compatible avec un MarketScanRun qui expose soit :
    - timeframe (FK)
    - timeframe_code (str)
    - ou rien du tout
    """

    REGIME_TREND_BULLISH = "TREND_BULLISH"
    REGIME_TREND_BEARISH = "TREND_BEARISH"
    REGIME_RANGE = "RANGE"
    REGIME_VOLATILE = "VOLATILE"
    REGIME_MIXED = "MIXED"

    @staticmethod
    def _to_decimal(value: Any, default: str = "0") -> Decimal:
        try:
            if value is None or value == "":
                return Decimal(default)
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal(default)

    @classmethod
    def _safe_timeframe_code_from_run(cls, market_scan_run) -> str:
        code = getattr(market_scan_run, "timeframe_code", None)
        if code:
            return str(code).strip()

        timeframe = getattr(market_scan_run, "timeframe", None)
        if timeframe is not None:
            tf_code = getattr(timeframe, "code", None)
            if tf_code:
                return str(tf_code).strip()

        return ""

    @classmethod
    def _safe_timeframe_from_rows(cls, rows: list[dict]) -> Timeframe | None:
        for row in rows or []:
            timeframe = row.get("timeframe")
            if timeframe is not None:
                return timeframe
        return None

    @classmethod
    def _resolve_timeframe(cls, market_scan_run, rows: list[dict]) -> Timeframe | None:
        """
        Résout un objet Timeframe si possible.
        """
        timeframe = getattr(market_scan_run, "timeframe", None)
        if timeframe is not None:
            return timeframe

        timeframe = cls._safe_timeframe_from_rows(rows)
        if timeframe is not None:
            return timeframe

        timeframe_code = cls._safe_timeframe_code_from_run(market_scan_run)
        if timeframe_code:
            return Timeframe.objects.filter(code=timeframe_code).first()

        return None

    @classmethod
    def _summarize_rows(cls, rows: list[dict]) -> dict[str, Any]:
        bullish = 0
        bearish = 0
        ranging = 0
        volatile = 0
        mixed = 0

        confidence_values: list[Decimal] = []
        trend_strength_values: list[Decimal] = []
        volatility_values: list[Decimal] = []

        for row in rows or []:
            features = row.get("features") or {}
            market_snapshot = row.get("market_snapshot") or {}

            close = cls._to_decimal(features.get("close"), "0")
            previous_close = cls._to_decimal(features.get("previous_close"), "0")
            atr = cls._to_decimal(features.get("atr_14"), "0")
            rsi = cls._to_decimal(features.get("rsi_14"), "50")
            macd = cls._to_decimal(features.get("macd"), "0")
            macd_signal = cls._to_decimal(features.get("macd_signal"), "0")

            confidence = Decimal("0.50")
            trend_strength = Decimal("0")
            volatility_score = Decimal("0")

            if previous_close > 0 and close > 0:
                price_delta_pct = abs((close - previous_close) / previous_close) * Decimal("100")
                trend_strength = price_delta_pct
                volatility_score = price_delta_pct

            if atr > 0 and close > 0:
                atr_pct = (atr / close) * Decimal("100")
                volatility_score = max(volatility_score, atr_pct)

            if close > previous_close and rsi >= Decimal("55") and macd >= macd_signal:
                bullish += 1
                confidence = Decimal("0.75")
            elif close < previous_close and rsi <= Decimal("45") and macd <= macd_signal:
                bearish += 1
                confidence = Decimal("0.75")
            elif volatility_score >= Decimal("1.5"):
                volatile += 1
                confidence = Decimal("0.65")
            elif abs(rsi - Decimal("50")) <= Decimal("5"):
                ranging += 1
                confidence = Decimal("0.60")
            else:
                mixed += 1
                confidence = Decimal("0.55")

            confidence_values.append(confidence)
            trend_strength_values.append(trend_strength)
            volatility_values.append(volatility_score)

        total = len(rows or [])
        avg_confidence = (
            sum(confidence_values, start=Decimal("0")) / Decimal(str(total))
            if total > 0 else Decimal("0")
        )
        avg_trend = (
            sum(trend_strength_values, start=Decimal("0")) / Decimal(str(total))
            if total > 0 else Decimal("0")
        )
        avg_volatility = (
            sum(volatility_values, start=Decimal("0")) / Decimal(str(total))
            if total > 0 else Decimal("0")
        )

        counts = {
            cls.REGIME_TREND_BULLISH: bullish,
            cls.REGIME_TREND_BEARISH: bearish,
            cls.REGIME_RANGE: ranging,
            cls.REGIME_VOLATILE: volatile,
            cls.REGIME_MIXED: mixed,
        }

        dominant_regime = max(counts.items(), key=lambda x: x[1])[0] if total > 0 else cls.REGIME_MIXED

        return {
            "total": total,
            "counts": counts,
            "dominant_regime": dominant_regime,
            "avg_confidence": float(avg_confidence),
            "avg_trend": float(avg_trend),
            "avg_volatility": float(avg_volatility),
        }

    @classmethod
    def _build_summary_text(cls, regime: str, stats: dict[str, Any]) -> str:
        total = stats.get("total", 0)
        avg_confidence = stats.get("avg_confidence", 0.0)
        avg_trend = stats.get("avg_trend", 0.0)
        avg_volatility = stats.get("avg_volatility", 0.0)

        label_map = {
            cls.REGIME_TREND_BULLISH: "marché haussier en tendance",
            cls.REGIME_TREND_BEARISH: "marché baissier en tendance",
            cls.REGIME_RANGE: "marché en range",
            cls.REGIME_VOLATILE: "marché volatil",
            cls.REGIME_MIXED: "marché mixte",
        }

        regime_label = label_map.get(regime, "marché mixte")

        return (
            f"Analyse sur {total} actif(s) : {regime_label}. "
            f"Confiance moyenne {avg_confidence:.2f}, "
            f"trend score moyen {avg_trend:.2f}, "
            f"volatility score moyen {avg_volatility:.2f}."
        )

    @classmethod
    @transaction.atomic
    def analyze(cls, market_scan_run, rows: list[dict]):
        """
        Analyse le régime de marché et persiste :
        - AgentRun
        - MarketRegimeSnapshot
        """
        started_at = timezone.now()

        agent_run = AgentRun.objects.create(
            agent_type="MARKET_REGIME",
            status="RUNNING",
            market_scan_run=market_scan_run,
            user=getattr(market_scan_run, "user", None),
            input_payload={
                "rows_count": len(rows or []),
                "timeframe_code": cls._safe_timeframe_code_from_run(market_scan_run),
            },
            started_at=started_at,
        )

        try:
            stats = cls._summarize_rows(rows or [])
            regime = stats["dominant_regime"]
            summary = cls._build_summary_text(regime, stats)
            timeframe = cls._resolve_timeframe(market_scan_run, rows or [])

            snapshot = MarketRegimeSnapshot.objects.create(
                market_scan_run=market_scan_run,
                timeframe=timeframe,
                regime=regime,
                confidence=stats["avg_confidence"],
                summary=summary,
                risk_posture=(
                    "DEFENSIVE" if regime == cls.REGIME_VOLATILE
                    else "AGGRESSIVE" if regime == cls.REGIME_TREND_BULLISH
                    else "CAUTIOUS" if regime == cls.REGIME_TREND_BEARISH
                    else "NEUTRAL"
                ),
                payload={
                    "counts": stats["counts"],
                    "total": stats["total"],
                    "trend_score": stats["avg_trend"],
                    "volatility_score": stats["avg_volatility"],
                    "timeframe_code": cls._safe_timeframe_code_from_run(market_scan_run),
                },
            )

            finished_at = timezone.now()
            runtime_ms = int((finished_at - started_at).total_seconds() * 1000)

            agent_run.status = "SUCCEEDED"
            agent_run.output_payload = {
                "snapshot_id": snapshot.id,
                "regime": snapshot.regime,
                "confidence": snapshot.confidence,
                "risk_posture": snapshot.risk_posture,
            }
            agent_run.finished_at = finished_at
            agent_run.runtime_ms = runtime_ms
            agent_run.save(update_fields=[
                "status",
                "output_payload",
                "finished_at",
                "runtime_ms",
                "updated_at",
            ])

            return snapshot

        except Exception as exc:
            finished_at = timezone.now()
            runtime_ms = int((finished_at - started_at).total_seconds() * 1000)

            agent_run.status = "FAILED"
            agent_run.error_message = str(exc)
            agent_run.finished_at = finished_at
            agent_run.runtime_ms = runtime_ms
            agent_run.save(update_fields=[
                "status",
                "error_message",
                "finished_at",
                "runtime_ms",
                "updated_at",
            ])
            raise