from __future__ import annotations

from decimal import Decimal
from django.db import transaction
from django.utils import timezone

from trading.models_ai import MarketScanRun, MarketOpportunity


# from .models_ai import MarketScanRun, MarketOpportunity


def _d(value, default="0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


class OpportunityEngine:
    @staticmethod
    @transaction.atomic
    def start_scan(source="SYSTEM", universe="DEFAULT", timeframe_code="5m", regime_snapshot=None):
        return MarketScanRun.objects.create(
            source=source,
            universe=universe,
            timeframe_code=timeframe_code,
            regime_snapshot=regime_snapshot or {},
            status="STARTED",
        )

    @staticmethod
    @transaction.atomic
    def create_opportunity(
        *,
        scan_run: MarketScanRun,
        asset,
        symbol: str,
        direction: str,
        entry_price,
        stop_loss,
        take_profit,
        confidence_score,
        setup_score,
        risk_score,
        reward_score,
        overall_score,
        regime_label=None,
        feature_snapshot=None,
        explanation=None,
        expires_in_minutes=30,
    ) -> MarketOpportunity:
        return MarketOpportunity.objects.create(
            scan_run=scan_run,
            asset=asset,
            symbol=symbol,
            asset_name=getattr(asset, "name", symbol) if asset else symbol,
            timeframe_code=scan_run.timeframe_code,
            direction=direction,
            entry_price=_d(entry_price),
            stop_loss=_d(stop_loss) if stop_loss is not None else None,
            take_profit=_d(take_profit) if take_profit is not None else None,
            confidence_score=_d(confidence_score),
            setup_score=_d(setup_score),
            risk_score=_d(risk_score),
            reward_score=_d(reward_score),
            overall_score=_d(overall_score),
            regime_label=regime_label,
            feature_snapshot=feature_snapshot or {},
            explanation=explanation or "",
            status="ACTIVE",
            expires_at=timezone.now() + timezone.timedelta(minutes=expires_in_minutes),
        )

    @staticmethod
    @transaction.atomic
    def finish_scan(scan_run: MarketScanRun, status="SUCCESS", message="", payload=None):
        scan_run.status = status
        scan_run.message = message
        scan_run.payload = payload or {}
        scan_run.finished_at = timezone.now()
        scan_run.save(update_fields=["status", "message", "payload", "finished_at", "updated_at"])
        return scan_run

    @staticmethod
    @transaction.atomic
    def expire_old_opportunities():
        now = timezone.now()
        qs = MarketOpportunity.objects.filter(status__in=["NEW", "ACTIVE"], expires_at__lt=now)
        count = qs.update(status="EXPIRED", updated_at=timezone.now())
        return count