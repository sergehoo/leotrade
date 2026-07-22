"""
Kill switch intelligent par stratégie.

Surveille les métriques d'apprentissage (LearningSnapshot) et met
automatiquement en pause les stratégies dégradées :
  - win rate sous le seuil après un échantillon suffisant,
  - expectancy négative (la stratégie perd de l'argent en moyenne).

Chaque coupure persiste un StrategyCircuitBreakerEvent (audit + réactivation
manuelle). Idempotent : une stratégie déjà coupée n'est pas re-coupée.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from .models import StrategyCircuitBreakerEvent

log = logging.getLogger("lyneci.risk.circuit_breaker")


class StrategyCircuitBreakerService:
    # Seuils de dégradation — un échantillon minimal évite de couper
    # une stratégie sur 2-3 trades malchanceux.
    MIN_TRADES = 10
    MIN_WIN_RATE = 0.35
    MIN_EXPECTANCY = 0.0

    @classmethod
    def evaluate_strategy(cls, strategy) -> StrategyCircuitBreakerEvent | None:
        """Évalue une stratégie active ; la coupe si dégradée.

        Retourne l'événement créé, ou None si la stratégie est saine,
        inactive, sans données suffisantes, ou déjà coupée.
        """
        from trading.models_hedge_fund import LearningSnapshot

        if not strategy.is_active:
            return None

        if StrategyCircuitBreakerEvent.objects.filter(
            strategy=strategy, is_active=True
        ).exists():
            return None

        snapshot = (
            LearningSnapshot.objects
            .filter(strategy=strategy)
            .order_by("-created_at")
            .first()
        )
        if snapshot is None or snapshot.total_trades < cls.MIN_TRADES:
            return None

        reason_code = None
        if snapshot.expectancy < cls.MIN_EXPECTANCY and snapshot.win_rate < cls.MIN_WIN_RATE:
            reason_code = "DEGRADED_WIN_RATE"
            reason = (
                f"Win rate {snapshot.win_rate:.1%} < {cls.MIN_WIN_RATE:.0%} "
                f"et expectancy {snapshot.expectancy:.4f} < 0 "
                f"sur {snapshot.total_trades} trades."
            )
        elif snapshot.expectancy < cls.MIN_EXPECTANCY:
            reason_code = "NEGATIVE_EXPECTANCY"
            reason = (
                f"Expectancy {snapshot.expectancy:.4f} < 0 "
                f"sur {snapshot.total_trades} trades "
                f"(win rate {snapshot.win_rate:.1%})."
            )

        if reason_code is None:
            return None

        return cls.trip(
            strategy,
            reason_code=reason_code,
            reason=reason,
            snapshot=snapshot,
        )

    @classmethod
    @transaction.atomic
    def trip(cls, strategy, *, reason_code: str, reason: str, snapshot=None,
             payload: dict | None = None) -> StrategyCircuitBreakerEvent:
        """Coupe la stratégie : pause + événement d'audit."""
        strategy.is_active = False
        strategy.status = "PAUSED"
        strategy.save(update_fields=["is_active", "status", "updated_at"])

        event = StrategyCircuitBreakerEvent.objects.create(
            strategy=strategy,
            reason_code=reason_code,
            reason=reason,
            win_rate=float(getattr(snapshot, "win_rate", 0.0) or 0.0),
            expectancy=float(getattr(snapshot, "expectancy", 0.0) or 0.0),
            total_trades=int(getattr(snapshot, "total_trades", 0) or 0),
            payload=payload or {
                "snapshot_id": getattr(snapshot, "id", None),
                "tripped_at": timezone.now().isoformat(),
            },
        )

        log.warning(
            "circuit_breaker.tripped strategy_id=%s reason=%s win_rate=%s expectancy=%s",
            strategy.id, reason_code, event.win_rate, event.expectancy,
        )

        from notifications.shortcuts import notify_admins
        notify_admins(
            "STRATEGY_CIRCUIT_BREAKER",
            title=f"Stratégie coupée : {strategy.name}",
            message=(
                f"Le kill switch intelligent a mis en pause « {strategy.name} » : {reason} "
                f"Réactivation possible après revue depuis l'admin ou la page stratégie."
            ),
            payload={"strategy_id": strategy.id, "reason_code": reason_code,
                     "win_rate": event.win_rate, "expectancy": event.expectancy},
            dedupe_key=f"circuit_breaker:{event.id}",
        )
        return event

    @classmethod
    @transaction.atomic
    def resolve(cls, strategy, *, user=None, reactivate: bool = False) -> int:
        """Résout les coupures actives ; réactive la stratégie si demandé."""
        events = StrategyCircuitBreakerEvent.objects.filter(
            strategy=strategy, is_active=True
        )
        count = events.update(
            is_active=False,
            resolved_at=timezone.now(),
            resolved_by=user,
        )
        if reactivate and count:
            strategy.is_active = True
            strategy.status = "PAPER" if strategy.status == "PAUSED" else strategy.status
            strategy.save(update_fields=["is_active", "status", "updated_at"])
        return count

    @classmethod
    def evaluate_all(cls) -> list[StrategyCircuitBreakerEvent]:
        """Évalue toutes les stratégies actives. Retourne les coupures créées."""
        from strategies.models import Strategy

        tripped = []
        for strategy in Strategy.objects.filter(is_active=True).iterator():
            try:
                event = cls.evaluate_strategy(strategy)
                if event is not None:
                    tripped.append(event)
            except Exception:
                log.exception("circuit_breaker.evaluate_failed strategy_id=%s", strategy.id)
        return tripped
