from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from django.core.cache import cache
from django.db import transaction

from brokers.models import BrokerConstraint
from brokers.services.base import BrokerConstraintSyncService
# from brokers.services_constraints import BrokerConstraintSyncService
from portfolio.services import PortfolioService
from risk.models import RiskDecision, RiskProfile
from risk.services import (
    PositionSizingService,
    RiskGuardService,
    RiskDecisionService,
)


def _d(value, default="0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


@dataclass
class RiskEngineDecision:
    accepted: bool
    decision: str
    reason: str

    requested_stake: Decimal
    approved_stake: Decimal

    requested_quantity: Decimal
    approved_quantity: Decimal

    requested_notional: Decimal
    approved_notional: Decimal

    expected_loss: Decimal
    expected_gain: Decimal
    risk_reward_ratio: Decimal

    risk_profile_id: Optional[int] = None
    risk_decision_id: Optional[int] = None
    payload: Optional[dict] = None


class RiskEngine:
    """
    Façade compatible avec :
        risk_decision = RiskEngine(portfolio).evaluate(signal)

    Elle :
    - charge le profil de risque
    - récupère les contraintes broker
    - calcule le sizing
    - applique le contrôle de risque
    - persiste une RiskDecision
    """

    def __init__(self, portfolio):
        self.portfolio = portfolio
        self.portfolio = PortfolioService.refresh_portfolio_metrics(self.portfolio)
        self.risk_profile = self._get_risk_profile()

    def _get_risk_profile(self) -> RiskProfile:
        return RiskGuardService.get_default_profile(self.portfolio)

    # TTL du cache Redis des contraintes broker (15 minutes).
    # Evite un appel réseau synchrone (~1-3s) à chaque évaluation de risque.
    # La invalidation explicite est faite par BrokerConstraintSyncService après
    # un sync réussi.
    _CONSTRAINT_CACHE_TTL = 900

    def _constraint_cache_key(self, symbol: str) -> str:
        broker_id = getattr(self.portfolio.broker_account, "broker", "unknown")
        return f"bc:{broker_id}:{symbol}"

    def _get_constraint(self, symbol: str):
        broker_account = self.portfolio.broker_account
        cache_key = self._constraint_cache_key(symbol)

        # 1. Tentative cache Redis (hit → 0 ms, pas de lock DB)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        # 2. Base de données locale
        constraint = BrokerConstraint.objects.filter(
            broker=broker_account.broker,
            symbol=symbol,
        ).first()

        if constraint is None:
            # 3. Sync réseau vers le broker (peut être lent — seulement si DB miss)
            try:
                constraint = BrokerConstraintSyncService.sync_symbol_constraint(
                    broker_account=broker_account,
                    symbol=symbol,
                )
            except Exception:
                pass

        if constraint is not None:
            # Stockage en cache — modèle Django serialisable via pickle par défaut
            cache.set(cache_key, constraint, self._CONSTRAINT_CACHE_TTL)

        return constraint

    def _extract_signal_payload(self, signal):
        strategy = getattr(signal, "strategy", None)
        asset = getattr(strategy, "asset", None) if strategy else None

        side = str(getattr(signal, "side", "BUY") or "BUY").upper()
        if side in {"LONG", "CALL"}:
            side = "BUY"
        elif side in {"SHORT", "PUT"}:
            side = "SELL"

        entry_price = _d(getattr(signal, "price", None))
        stop_loss = getattr(signal, "stop_loss", None)
        take_profit = getattr(signal, "take_profit", None)
        confidence = _d(getattr(signal, "confidence", None), "0")

        symbol = None
        if asset and getattr(asset, "symbol", None):
            symbol = asset.symbol
        elif hasattr(signal, "symbol") and getattr(signal, "symbol", None):
            symbol = signal.symbol
        else:
            raise ValueError("Impossible de déterminer le symbole du signal.")

        return {
            "signal": signal,
            "asset": asset,
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "stop_loss": _d(stop_loss) if stop_loss is not None else None,
            "take_profit": _d(take_profit) if take_profit is not None else None,
            "confidence": confidence,
        }

    def _compute_requested_stake(self, signal_payload: dict) -> Decimal:
        """
        Détermine le stake à utiliser pour le signal.
        Priorités :
        1. signal.stake_amount si présent
        2. signal.amount si présent
        3. allocation heuristique basée sur le profil de risque
        """
        signal = signal_payload["signal"]

        for attr in ("stake_amount", "amount", "requested_stake", "capital"):
            if hasattr(signal, attr):
                value = getattr(signal, attr, None)
                value = _d(value)
                if value > 0:
                    return value

        equity = _d(self.portfolio.equity)
        available_cash = _d(self.portfolio.available_cash)
        max_risk_pct = _d(self.risk_profile.max_risk_per_trade) / Decimal("100")

        heuristic = min(
            available_cash * Decimal("0.10"),
            equity * max_risk_pct * Decimal("4"),
        )

        if heuristic <= 0:
            heuristic = min(available_cash, Decimal("100"))

        return heuristic.quantize(Decimal("0.01"))

    def _build_result(
        self,
        *,
        approval,
        sizing,
        risk_decision: Optional[RiskDecision],
        reason_override: str = "",
    ) -> RiskEngineDecision:
        reason = reason_override or approval.blocking_reason or ""

        return RiskEngineDecision(
            accepted=approval.decision in {"APPROVE", "REDUCE"},
            decision=approval.decision,
            reason=reason,
            requested_stake=sizing.requested_stake,
            approved_stake=approval.approved_stake,
            requested_quantity=sizing.quantity,
            approved_quantity=approval.approved_quantity,
            requested_notional=sizing.notional,
            approved_notional=approval.approved_notional,
            expected_loss=approval.expected_loss,
            expected_gain=approval.expected_gain,
            risk_reward_ratio=approval.risk_reward_ratio,
            risk_profile_id=self.risk_profile.id if self.risk_profile else None,
            risk_decision_id=risk_decision.id if risk_decision else None,
            payload={
                "approval": approval.payload,
                "sizing_reason": sizing.reason,
            },
        )

    @transaction.atomic
    def evaluate(self, signal) -> RiskEngineDecision:
        signal_payload = self._extract_signal_payload(signal)

        entry_price = signal_payload["entry_price"]
        stop_loss = signal_payload["stop_loss"]
        take_profit = signal_payload["take_profit"]
        symbol = signal_payload["symbol"]
        side = signal_payload["side"]
        asset = signal_payload["asset"]
        confidence = signal_payload["confidence"]

        if entry_price <= 0:
            return RiskEngineDecision(
                accepted=False,
                decision="REJECT",
                reason="Prix d'entrée invalide sur le signal.",
                requested_stake=Decimal("0.00"),
                approved_stake=Decimal("0.00"),
                requested_quantity=Decimal("0"),
                approved_quantity=Decimal("0"),
                requested_notional=Decimal("0.00"),
                approved_notional=Decimal("0.00"),
                expected_loss=Decimal("0.00"),
                expected_gain=Decimal("0.00"),
                risk_reward_ratio=Decimal("0.00"),
                risk_profile_id=self.risk_profile.id if self.risk_profile else None,
                risk_decision_id=None,
                payload={"symbol": symbol},
            )

        if stop_loss is None or stop_loss <= 0:
            return RiskEngineDecision(
                accepted=False,
                decision="REJECT",
                reason="Stop loss invalide ou absent.",
                requested_stake=Decimal("0.00"),
                approved_stake=Decimal("0.00"),
                requested_quantity=Decimal("0"),
                approved_quantity=Decimal("0"),
                requested_notional=Decimal("0.00"),
                approved_notional=Decimal("0.00"),
                expected_loss=Decimal("0.00"),
                expected_gain=Decimal("0.00"),
                risk_reward_ratio=Decimal("0.00"),
                risk_profile_id=self.risk_profile.id if self.risk_profile else None,
                risk_decision_id=None,
                payload={"symbol": symbol},
            )

        requested_stake = self._compute_requested_stake(signal_payload)
        constraint = self._get_constraint(symbol)

        min_qty = _d(getattr(constraint, "min_qty", Decimal("0.00000001")))
        qty_step = _d(getattr(constraint, "qty_step", Decimal("0.00000001")))
        min_notional = _d(getattr(constraint, "min_notional", Decimal("0")))
        leverage = Decimal("1")

        try:
            sizing = PositionSizingService.compute(
                portfolio=self.portfolio,
                risk_profile=self.risk_profile,
                entry_price=entry_price,
                stop_loss=stop_loss,
                requested_stake=requested_stake,
                min_qty=min_qty,
                qty_step=qty_step,
                min_notional=min_notional,
                leverage=leverage,
            )
        except Exception as exc:
            return RiskEngineDecision(
                accepted=False,
                decision="REJECT",
                reason=f"Erreur sizing: {exc}",
                requested_stake=requested_stake,
                approved_stake=Decimal("0.00"),
                requested_quantity=Decimal("0"),
                approved_quantity=Decimal("0"),
                requested_notional=Decimal("0.00"),
                approved_notional=Decimal("0.00"),
                expected_loss=Decimal("0.00"),
                expected_gain=Decimal("0.00"),
                risk_reward_ratio=Decimal("0.00"),
                risk_profile_id=self.risk_profile.id if self.risk_profile else None,
                risk_decision_id=None,
                payload={"symbol": symbol},
            )

        approval = RiskGuardService.validate_trade(
            portfolio=self.portfolio,
            symbol=symbol,
            asset=asset,
            side=side,
            requested_stake=sizing.requested_stake,
            approved_quantity=sizing.quantity,
            approved_notional=sizing.notional,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=confidence,
            signal=signal,
            trade_idea=None,
        )

        risk_decision = RiskDecisionService.persist_decision(
            portfolio=self.portfolio,
            risk_profile=self.risk_profile,
            symbol=symbol,
            asset_class=getattr(asset, "asset_class", None),
            side=side,
            requested_stake=sizing.requested_stake,
            approved_result=approval,
            requested_quantity=sizing.quantity,
            requested_notional=sizing.notional,
            signal=signal,
            trade_idea=None,
            order=None,
        )

        return self._build_result(
            approval=approval,
            sizing=sizing,
            risk_decision=risk_decision,
        )