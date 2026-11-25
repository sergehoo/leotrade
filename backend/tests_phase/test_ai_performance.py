"""
Phase IA copilote — schéma de décision enrichi + performance IA.

Couverture :
  1. AIDecision transporte les champs copilote (scénarios, invalidation,
     probabilité) et le parsing Claude les extrait/borne correctement.
  2. Le provider heuristique produit une analyse non générique.
  3. AIPerformanceService.summary agrège les résultats réels
     (hit rate, calibration, score) et reste sain sans données.
  4. PredictionEvaluationService confronte les prédictions aux bougies
     réelles et calcule l'accuracy.
  5. L'endpoint /ai/performance/ répond avec la structure attendue.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from ai_engine.providers.base import AIDecision, MarketContext
from ai_engine.providers.claude import _parsed_to_decision
from ai_engine.providers.heuristic import HeuristicProvider
from ai_engine.services_performance import (
    AIPerformanceService,
    PredictionEvaluationService,
)


# ─────────────────────────────────────────────────────────────────────────────
#  1. Schéma enrichi
# ─────────────────────────────────────────────────────────────────────────────

def test_parsed_to_decision_extracts_copilot_fields():
    parsed = {
        "decision": "EXECUTE",
        "confidence": 0.72,
        "direction": "LONG",
        "rationale": "RSI à 28 sous la borne 30, MACD repasse positif.",
        "primary_scenario": "Rebond vers 105 sous 4 bougies",
        "alternative_scenario": "Cassure de 98 et poursuite baissière",
        "invalidation": "Clôture sous 98.0",
        "probability_estimate": 1.4,  # hors borne → doit être clampé à 1.0
        "risks": ["volatilité élevée"],
    }
    d = _parsed_to_decision(
        parsed, provider="CLAUDE", model_name="test",
        raw_response={}, latency_ms=1, tokens_in=0, tokens_out=0,
        cost_usd=Decimal("0"),
    )
    assert d.primary_scenario.startswith("Rebond")
    assert d.alternative_scenario.startswith("Cassure")
    assert d.invalidation == "Clôture sous 98.0"
    assert d.probability_estimate == 1.0  # clampé


def test_parsed_to_decision_defaults_without_copilot_fields():
    d = _parsed_to_decision(
        {"decision": "WATCH", "confidence": 0.4},
        provider="CLAUDE", model_name="test",
        raw_response={}, latency_ms=1, tokens_in=0, tokens_out=0,
        cost_usd=Decimal("0"),
    )
    assert d.primary_scenario == ""
    assert d.probability_estimate is None


def test_heuristic_provider_fills_scenarios():
    ctx = MarketContext(
        symbol="R_100",
        last_price=Decimal("100"),
        indicators={"rsi": 25, "macd_hist": 0.5, "sma_20": 101, "sma_50": 99, "atr": 1.2},
        available_cash=Decimal("1000"),
        max_risk_per_trade_pct=1.0,
        max_open_positions=5,
        current_open_positions=0,
    )
    d = HeuristicProvider().advise(ctx)
    assert d.direction == "LONG"
    assert d.primary_scenario
    assert d.alternative_scenario
    assert d.invalidation
    assert 0.0 <= d.probability_estimate <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
#  2. Performance IA — fixtures boucle fermée
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def asset_tf(db):
    from market.models import Asset, Timeframe
    asset = Asset.objects.create(
        symbol="R_100", name="Volatility 100", asset_class="SYNTHETIC",
        exchange="DERIV", is_active=True,
    )
    tf, _ = Timeframe.objects.get_or_create(code="M5", defaults={"minutes": 5})
    return asset, tf


def _make_idea_with_outcome(user, asset, tf, *, outcome, confidence, pnl="10.00"):
    from ai_engine.models import AIDecisionLog
    from trading.models import TradeIdea, TradeIdeaFeedback

    idea = TradeIdea.objects.create(
        user=user, asset=asset, timeframe=tf,
        symbol=asset.symbol, direction="BUY",
        entry_price=Decimal("100"), stop_loss=Decimal("98"),
        take_profit=Decimal("104"),
        confidence_score=confidence, overall_score=0.7,
        status="EXECUTED",
    )
    TradeIdeaFeedback.objects.create(
        idea=idea, outcome=outcome,
        pnl_amount=Decimal(pnl) if outcome == "WIN" else -Decimal(pnl),
    )
    AIDecisionLog.objects.create(
        user=user, symbol=asset.symbol, provider="CLAUDE",
        decision="EXECUTE", confidence=confidence,
        trade_idea=idea,
        analysis={"primary_scenario": "test", "probability_estimate": confidence},
    )
    return idea


@pytest.mark.django_db
def test_performance_summary_empty_is_safe(user):
    summary = AIPerformanceService.summary(user=user)
    assert summary["sample_size"] == 0
    assert summary["hit_rate"] is None
    assert summary["ai_score"] is None


@pytest.mark.django_db
def test_performance_summary_aggregates_real_outcomes(user, asset_tf):
    asset, tf = asset_tf
    # 2 gains à haute confiance, 1 perte à basse confiance → bien calibré
    _make_idea_with_outcome(user, asset, tf, outcome="WIN", confidence=0.85)
    _make_idea_with_outcome(user, asset, tf, outcome="WIN", confidence=0.80)
    _make_idea_with_outcome(user, asset, tf, outcome="LOSS", confidence=0.55)

    summary = AIPerformanceService.summary(user=user)

    assert summary["sample_size"] == 3
    assert summary["wins"] == 2
    assert summary["losses"] == 1
    assert summary["hit_rate"] == pytest.approx(2 / 3, abs=1e-3)
    assert summary["well_calibrated"] is True
    assert summary["ai_score"] is not None and summary["ai_score"] > 0


@pytest.mark.django_db
def test_recommendation_history_includes_outcome(user, asset_tf):
    asset, tf = asset_tf
    _make_idea_with_outcome(user, asset, tf, outcome="WIN", confidence=0.9)

    history = AIPerformanceService.recommendation_history(user=user)

    assert len(history) == 1
    assert history[0]["outcome"] == "WIN"
    assert history[0]["analysis"]["primary_scenario"] == "test"


# ─────────────────────────────────────────────────────────────────────────────
#  3. Prévision vs réalité
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_prediction_evaluation_against_real_candles(user, asset_tf):
    from market.models import Candle
    from strategies.models import Strategy, StrategyPrediction

    asset, tf = asset_tf
    strategy = Strategy.objects.create(
        name="Pred Strategy", asset=asset, timeframe=tf,
        strategy_type="RULE", status="PAPER", is_active=True,
    )

    t0 = timezone.now() - timedelta(hours=2)
    # Prédiction UP… suivie d'une bougie réellement haussière
    StrategyPrediction.objects.create(
        strategy=strategy, candle_time=t0, predicted_label="UP",
    )
    # Prédiction DOWN… suivie de la même bougie haussière → incorrecte
    StrategyPrediction.objects.create(
        strategy=strategy, candle_time=t0 + timedelta(minutes=1),
        predicted_label="DOWN",
    )
    Candle.objects.create(
        asset=asset, timeframe=tf,
        open_time=t0 + timedelta(minutes=5),
        close_time=t0 + timedelta(minutes=10),
        open=Decimal("100"), high=Decimal("103"),
        low=Decimal("99"), close=Decimal("102"),
    )

    result = PredictionEvaluationService.evaluate_pending()

    assert result == {"evaluated": 2, "correct": 1}
    up = StrategyPrediction.objects.get(predicted_label="UP")
    down = StrategyPrediction.objects.get(predicted_label="DOWN")
    assert up.is_correct is True and up.actual_label == "UP"
    assert down.is_correct is False

    acc = PredictionEvaluationService.accuracy()
    assert acc["sample_size"] == 2
    assert acc["accuracy"] == 0.5


@pytest.mark.django_db
def test_prediction_without_next_candle_stays_pending(user, asset_tf):
    from strategies.models import Strategy, StrategyPrediction

    asset, tf = asset_tf
    strategy = Strategy.objects.create(
        name="Pending Strategy", asset=asset, timeframe=tf,
        strategy_type="RULE", status="PAPER", is_active=True,
    )
    StrategyPrediction.objects.create(
        strategy=strategy, candle_time=timezone.now(), predicted_label="UP",
    )

    result = PredictionEvaluationService.evaluate_pending()

    assert result["evaluated"] == 0
    assert StrategyPrediction.objects.filter(is_correct__isnull=True).count() == 1


# ─────────────────────────────────────────────────────────────────────────────
#  4. Endpoint Centre IA
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_ai_performance_endpoint(client, user):
    client.force_login(user)
    resp = client.get(reverse("ai_engine:ai_performance"))
    assert resp.status_code == 200
    payload = resp.json()
    assert set(payload.keys()) == {"summary", "history", "prediction_accuracy"}
    assert payload["summary"]["sample_size"] == 0
