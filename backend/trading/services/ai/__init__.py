"""
trading.services.ai
-------------------

New AI subsystem for Lyneci. Replaces the previous heuristic blob in
``opportunity_scoring.py`` with a modular pipeline:

- :mod:`trading.services.ai.features`  → robust technical features
- :mod:`trading.services.ai.regime`    → trend / range / chop classification
- :mod:`trading.services.ai.patterns`  → breakout / reversal / continuation
- :mod:`trading.services.ai.scoring`   → multi-factor confidence scoring
- :mod:`trading.services.ai.feedback`  → learn from past trades

Each layer is intentionally independent — you can plug a real ML model on
top of features without rewriting the others.
"""

from .features import compute_features, FeatureBundle
from .regime import detect_regime, MarketRegime
from .patterns import detect_patterns, DetectedPattern
from .scoring import score_opportunity, OpportunityScore
from .feedback import StrategyFeedback, update_strategy_confidence

__all__ = [
    "compute_features",
    "FeatureBundle",
    "detect_regime",
    "MarketRegime",
    "detect_patterns",
    "DetectedPattern",
    "score_opportunity",
    "OpportunityScore",
    "StrategyFeedback",
    "update_strategy_confidence",
]
