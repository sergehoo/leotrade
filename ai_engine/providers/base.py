"""
ai_engine/providers/base.py
===========================

Contrat commun pour tous les providers (Claude API, Ollama, Heuristic).

Le provider reçoit un `MarketContext` structuré et doit retourner un `AIDecision`
strictement typé. C'est le contrat unique sur lequel l'orchestrateur s'appuie.

Aucun provider ne fait de I/O bloquante au-delà de son scope (HTTP API call).
Aucun provider n'écrit en DB (c'est le rôle de AITradeAdvisor).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal


class ProviderUnavailable(Exception):
    """Le provider est indisponible (token manquant, réseau down, quota dépassé…)."""


@dataclass
class MarketContext:
    """
    Snapshot des features marché + contraintes risque, envoyé au provider.
    """
    symbol: str
    timeframe: str = "5m"
    direction_hint: str | None = None        # "LONG" / "SHORT" / None

    last_price: Decimal | None = None
    indicators: dict = field(default_factory=dict)   # rsi, macd, sma20/50, atr, etc.
    recent_candles: list[dict] = field(default_factory=list)  # OHLCV dernières N bougies
    regime: str | None = None                # "trending" / "ranging" / "high_vol"

    # Contraintes risque
    portfolio_balance: Decimal | None = None
    portfolio_equity: Decimal | None = None
    available_cash: Decimal | None = None
    max_risk_per_trade_pct: float | None = None
    max_open_positions: int | None = None
    current_open_positions: int = 0

    # Historique de performance pertinent
    recent_outcomes: list[str] = field(default_factory=list)  # ["WIN", "LOSS", "WIN"...]
    user_objective: str = ""                  # texte libre du TradingIntent


@dataclass
class AIDecision:
    """
    Réponse normalisée d'un provider.
    """
    decision: str = "ABSTAIN"          # EXECUTE | PLAN | WATCH | REJECT | ABSTAIN
    confidence: float = 0.0            # 0.0 → 1.0
    direction: str | None = None       # "LONG" / "SHORT"
    expected_rr: float | None = None
    suggested_stake: Decimal | None = None
    suggested_stop_loss: Decimal | None = None
    suggested_take_profit: Decimal | None = None
    rationale: str = ""
    risks: list[str] = field(default_factory=list)

    # Métadonnées techniques (rempli par l'orchestrator)
    provider: str = ""
    model_name: str = ""
    raw_response: dict = field(default_factory=dict)
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = Decimal("0")


class BaseAIProvider(ABC):
    """
    Interface stricte. Toute nouvelle intégration LLM doit implémenter advise().
    """

    name: str = "base"
    model_name: str = ""

    @abstractmethod
    def is_available(self) -> bool:
        """Retourne True si le provider est utilisable maintenant (token / endpoint)."""
        ...

    @abstractmethod
    def advise(self, context: MarketContext) -> AIDecision:
        """
        Demande un avis au provider. Doit lever ProviderUnavailable si le provider
        plante en cours d'exécution (timeout, 5xx, etc.) — NE PAS retourner une
        décision dégradée silencieusement, l'orchestrateur s'occupe du fallback.
        """
        ...
