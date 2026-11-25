"""
ai_engine/integrations.py
=========================

Glue entre AITradeAdvisor et le reste de Lyneci :
  - build_context_from_trade_idea(idea) → MarketContext rempli
  - advise_for_trade_idea(idea, user)   → AIDecision + persistance

Le but est que les callers métier (trading/tasks_ai.py, dashboard, vues admin)
n'aient PAS à connaître les internals des providers.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.utils import timezone

from .providers.base import MarketContext
from .services import AITradeAdvisor


log = logging.getLogger("lyneci.ai_engine.integrations")


def _safe_decimal(v):
    if v is None: return None
    try: return Decimal(str(v))
    except Exception: return None


def build_context_from_trade_idea(idea, *, portfolio=None) -> MarketContext:
    """
    Construit un MarketContext à partir d'un trading.TradeIdea + état du portfolio.
    Tolérant aux modèles partiellement remplis.
    """
    from market.models import Candle

    # Indicateurs (au cas où l'idea les transporte ; sinon on prend ce qu'on a)
    indicators = {}
    feature = getattr(idea, "feature", None) or getattr(idea, "market_feature", None)
    if feature:
        for f in ("rsi_14", "macd", "macd_signal", "macd_hist",
                  "sma_20", "sma_50", "atr_14", "bollinger_upper", "bollinger_lower"):
            v = getattr(feature, f, None)
            if v is not None:
                key = f.replace("rsi_14", "rsi").replace("atr_14", "atr")
                try:
                    indicators[key] = float(v)
                except Exception:
                    indicators[key] = v

    # Récentes bougies (10) — best effort
    recent_candles = []
    asset = getattr(idea, "asset", None)
    timeframe = getattr(idea, "timeframe", None)
    if asset and timeframe:
        candles_qs = Candle.objects.filter(
            asset=asset, timeframe=timeframe,
        ).order_by("-open_time")[:10]
        for c in candles_qs:
            recent_candles.append({
                "t": c.open_time.isoformat() if c.open_time else None,
                "o": str(c.open), "h": str(c.high),
                "l": str(c.low), "c": str(c.close),
                "v": str(c.volume) if c.volume is not None else None,
            })
        recent_candles.reverse()

    # Portefeuille
    pf = portfolio or getattr(idea, "portfolio", None)
    pf_balance = pf_equity = pf_cash = None
    max_risk_pct = None
    max_open = None
    current_open = 0
    if pf:
        pf_balance = getattr(pf, "current_balance", None)
        pf_equity = getattr(pf, "equity", None)
        pf_cash = getattr(pf, "available_cash", None)
        # Lookup risk profile (best effort)
        try:
            from risk.services import RiskGuardService
            profile = RiskGuardService.get_default_profile(pf)
            if profile:
                max_risk_pct = float(getattr(profile, "max_risk_per_trade", 1) or 1)
                max_open = int(getattr(profile, "max_open_positions", 0) or 0)
        except Exception:
            pass
        try:
            from portfolio.models import Position
            current_open = Position.objects.filter(
                portfolio=pf, status__in=["OPEN", "PARTIALLY_CLOSED"],
            ).count()
        except Exception:
            pass

    # Régime de marché (si dispo)
    regime = None
    try:
        from trading.models_hedge_fund import MarketRegimeState
        last_regime = MarketRegimeState.objects.order_by("-created_at").first()
        if last_regime:
            regime = getattr(last_regime, "regime", None) or getattr(last_regime, "label", None)
    except Exception:
        pass

    return MarketContext(
        symbol=getattr(idea, "symbol", "") or (asset.symbol if asset else "") or "",
        timeframe=str(getattr(timeframe, "code", "") or "5m"),
        direction_hint=getattr(idea, "direction", None),
        last_price=_safe_decimal(getattr(idea, "entry_price", None)),
        indicators=indicators,
        recent_candles=recent_candles,
        regime=regime,
        portfolio_balance=_safe_decimal(pf_balance),
        portfolio_equity=_safe_decimal(pf_equity),
        available_cash=_safe_decimal(pf_cash),
        max_risk_per_trade_pct=max_risk_pct,
        max_open_positions=max_open,
        current_open_positions=current_open,
        recent_outcomes=[],  # à enrichir plus tard via TradeIdeaFeedback
        user_objective=getattr(idea, "objective", "") or "",
    )


def advise_for_trade_idea(idea, *, user=None, portfolio=None):
    """
    Demande un avis IA pour une trade idea. Persiste le AIDecisionLog.
    Retourne l'AIDecision.
    """
    ctx = build_context_from_trade_idea(idea, portfolio=portfolio)
    return AITradeAdvisor.advise(
        context=ctx, user=user, portfolio=portfolio, trade_idea=idea,
    )
