from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from django.utils import timezone

from market.models import MarketFeature
from strategies.models import Strategy, Signal, StrategyPrediction
from .ml import StrategyModelService
from .risk_guard import StrategyRiskGuard
from .execution_router import StrategyExecutionRouter


class SignalEngineService:
    FEATURE_FIELDS = [
        "rsi_14",
        "macd",
        "macd_signal",
        "sma_20",
        "sma_50",
        "atr_14",
        "bb_high",
        "bb_low",
        "returns_1",
        "returns_5",
        "volatility_20",
    ]

    @classmethod
    def get_latest_feature_snapshot(cls, strategy: Strategy) -> MarketFeature | None:
        return (
            MarketFeature.objects
            .filter(asset=strategy.asset, timeframe=strategy.timeframe)
            .order_by("-candle_time")
            .first()
        )

    @classmethod
    def build_features_dict(cls, feature_obj: MarketFeature) -> dict:
        return {
            field: getattr(feature_obj, field, 0.0) or 0.0
            for field in cls.FEATURE_FIELDS
        }

    @classmethod
    def compute_sl_tp(cls, strategy: Strategy, price: Decimal, atr: float | None, side: str) -> tuple[
        Decimal | None, Decimal | None]:
        if not atr or atr <= 0:
            return None, None

        atr_dec = Decimal(str(atr))
        risk_mult = Decimal(str(strategy.parameters.get("atr_stop_mult", 1.5)))
        reward_mult = Decimal(str(strategy.parameters.get("atr_tp_mult", 3.0)))

        if side == "BUY":
            sl = price - (atr_dec * risk_mult)
            tp = price + (atr_dec * reward_mult)
        elif side == "SELL":
            sl = price + (atr_dec * risk_mult)
            tp = price - (atr_dec * reward_mult)
        else:
            return None, None

        return sl, tp

    @classmethod
    def predict_signal(cls, strategy: Strategy) -> dict:
        feature_obj = cls.get_latest_feature_snapshot(strategy)
        if not feature_obj:
            raise ValueError("Aucune feature disponible pour cette stratégie.")

        features = cls.build_features_dict(feature_obj)

        service = StrategyModelService(
            model_path=strategy.model_path,
            backend=strategy.parameters.get("ml_backend")
        )
        result = service.predict(features)

        StrategyPrediction.objects.create(
            strategy=strategy,
            candle_time=feature_obj.candle_time,
            predicted_label=result.get("side", ""),
            predicted_score=result.get("confidence", 0.0),
            probability_up=result.get("probabilities", {}).get("BUY", 0.0),
            probability_down=result.get("probabilities", {}).get("SELL", 0.0),
            raw_output=result,
            features_snapshot=features,
        )

        return {
            "feature_obj": feature_obj,
            "features": features,
            "prediction": result,
        }

    @classmethod
    def create_signal(cls, strategy: Strategy, prediction_payload: dict) -> Signal:
        feature_obj = prediction_payload["feature_obj"]
        features = prediction_payload["features"]
        prediction = prediction_payload["prediction"]

        side = prediction["side"]
        confidence = prediction["confidence"]

        ok, reason = StrategyRiskGuard.can_emit_signal(strategy)
        if not ok:
            raise ValueError(reason)

        ok, reason = StrategyRiskGuard.passes_confidence_threshold(strategy, confidence)
        if not ok:
            raise ValueError(reason)

        ok, reason = StrategyRiskGuard.daily_signal_limit_ok(strategy)
        if not ok:
            raise ValueError(reason)

        price = Decimal(str(feature_obj.asset.candles.filter(
            timeframe=strategy.timeframe,
            open_time=feature_obj.candle_time
        ).values_list("close", flat=True).first() or 0))

        sl, tp = cls.compute_sl_tp(strategy, price, feature_obj.atr_14, side)

        signal = Signal.objects.create(
            strategy=strategy,
            candle_time=feature_obj.candle_time,
            side=side,
            confidence=confidence,
            price=price,
            stop_loss=sl,
            take_profit=tp,
            reason=f"Signal IA généré automatiquement ({prediction.get('backend')}).",
            features_snapshot=features,
            model_output=prediction,
            expires_at=feature_obj.candle_time + timedelta(seconds=strategy.run_interval_seconds * 2),
            status="NEW",
        )
        return signal

    @classmethod
    def evaluate_and_route(cls, strategy: Strategy) -> Signal:
        payload = cls.predict_signal(strategy)
        signal = cls.create_signal(strategy, payload)
        StrategyExecutionRouter.route(signal)
        return signal
