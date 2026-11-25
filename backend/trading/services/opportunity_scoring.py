from __future__ import annotations

from typing import Any

from trading.services.ai.features import FeatureBundle
from trading.services.ai.scoring import score_opportunity


class OpportunityScoringService:
    """Compatibility facade over the production multi-factor scorer."""

    @staticmethod
    def clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
        return max(min_value, min(max_value, value))

    @staticmethod
    def _snapshot(features: dict[str, Any]) -> dict[str, float]:
        snapshot: dict[str, float] = {}
        for key, value in (features or {}).items():
            try:
                snapshot[key] = float(value)
            except (TypeError, ValueError):
                continue
        return snapshot

    @classmethod
    def score(
        cls,
        features: dict,
        *,
        feature_bundle: FeatureBundle | None = None,
        feedback_multiplier: float = 1.0,
    ) -> dict:
        bundle = feature_bundle or FeatureBundle(snapshot=cls._snapshot(features))
        result = score_opportunity(
            bundle,
            feedback_multiplier=feedback_multiplier,
        )
        return {
            "direction": result.side,
            "confidence_score": result.confidence,
            "setup_score": result.setup_score,
            "risk_score": result.risk_score,
            "reward_score": result.reward_score,
            "overall_score": result.overall_score,
            "trend_score": result.trend_score,
            "momentum_score": result.momentum_score,
            "volatility_score": result.volatility_score,
            "volume_score": result.volume_score,
            "regime": result.regime,
            "patterns": [
                {
                    "label": pattern.label,
                    "direction": pattern.direction,
                    "strength": pattern.strength,
                    "description": pattern.description,
                }
                for pattern in result.patterns
            ],
            "scoring_payload": result.payload,
        }

    @classmethod
    def choose_direction(
        cls,
        features: dict,
        *,
        feature_bundle: FeatureBundle | None = None,
    ) -> str:
        return cls.score(features, feature_bundle=feature_bundle)["direction"]
