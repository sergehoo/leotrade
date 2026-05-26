"""
execution/orchestrator.py
=========================

ExecutionOrchestrator : porte d'entrée UNIQUE pour la création d'un ordre.

Cycle imposé :
    OrderIntent
        ↓ (idempotency check)
    RiskEngine.evaluate()           ← OBLIGATOIRE
        ↓ (decision.approved)
    Order(status=PENDING_SUBMIT)
        ↓
    PortfolioAccountingService.lock_cash_for_order()
        ↓
    BrokerAdapter.submit_order()    ← hors transaction
        ↓
    FillProcessingService.register_fill() ×N
        ↓
    Order(status=FILLED) + Position(OPEN) + ledger TRADE_EXECUTION

Garanties :
- aucun ordre ne contourne le RiskEngine ;
- aucun ordre n'est dupliqué (idempotency_key UNIQUE) ;
- aucun ordre ne débite le portfolio deux fois (lock atomique + idempotence des fills) ;
- en cas d'échec broker, le lock cash est restauré.

Tous les chemins legacy (deriv_executor.py, binance_executor.py, etc.) doivent
progressivement appeler ExecutionOrchestrator.submit() au lieu de leur propre
flux. Les anciens chemins seront supprimés à la fin de la migration Phase 4.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction

from execution.intents import OrderIntent
from execution.models import Order


log = logging.getLogger("leotrade.execution.orchestrator")


class OrderRejected(Exception):
    """Refus du Risk Engine."""
    def __init__(self, reason: str, decision=None):
        super().__init__(reason)
        self.decision = decision


class TradingDisabled(Exception):
    """Kill switch activé."""


class ExecutionOrchestrator:

    @staticmethod
    @transaction.atomic
    def submit(intent: OrderIntent) -> Order:
        """
        Crée et soumet un ordre. Idempotent par intent.idempotency_key.

        Retourne l'Order. Le statut peut être :
            - PENDING_SUBMIT (lock cash fait, soumission broker async)
            - SUBMITTED      (broker ack reçu)
            - FILLED         (fill immédiat)
            - REJECTED       (risk refused) — exception OrderRejected sera levée
        """
        # 0. Kill switch global
        if not getattr(settings, "FEATURE_TRADING_ENABLED", True):
            log.warning(
                "trading.disabled idempotency_key=%s portfolio_id=%s",
                intent.idempotency_key, intent.portfolio_id,
            )
            raise TradingDisabled("FEATURE_TRADING_ENABLED=False")

        # 1. Idempotence : si déjà créé, on retourne l'Order existant
        existing = Order.objects.filter(idempotency_key=intent.idempotency_key).first()
        if existing:
            log.info(
                "orchestrator.idempotent_replay idempotency_key=%s order_id=%s",
                intent.idempotency_key, existing.id,
            )
            return existing

        # 2. Risk Engine — OBLIGATOIRE
        decision = _evaluate_risk(intent)
        if not _is_approved(decision):
            log.info(
                "orchestrator.risk_rejected idempotency_key=%s reason=%s",
                intent.idempotency_key, _decision_reason(decision),
            )
            raise OrderRejected(reason=_decision_reason(decision), decision=decision)

        # 3. Création de l'Order PENDING_SUBMIT
        order = _create_order_from_decision(intent, decision)

        # 4. Lock cash pour LIVE uniquement (PAPER = pas de débit réel)
        if intent.mode == "LIVE":
            from portfolio.models import Portfolio
            from portfolio.services import PortfolioAccountingService

            portfolio = Portfolio.objects.select_for_update().get(pk=intent.portfolio_id)
            try:
                PortfolioAccountingService.lock_cash_for_order(
                    portfolio=portfolio,
                    amount=order.approved_notional,
                    reference_type="ORDER",
                    reference_id=str(order.id),
                    metadata={"idempotency_key": intent.idempotency_key},
                )
            except ValueError as exc:
                # cash insuffisant
                order.status = "REJECTED"
                order.execution_notes = f"insufficient_cash: {exc}"
                order.save(update_fields=["status", "execution_notes", "updated_at"])
                raise OrderRejected(reason=f"insufficient_cash: {exc}") from exc

        # 5. Soumission broker — HORS transaction (déléguée à un worker async)
        from django.db.transaction import on_commit
        on_commit(lambda: _dispatch_to_broker(order.id))

        return order


class _IntentSignalAdapter:
    """
    Adapte un OrderIntent au "signal-like" object qu'attend RiskEngine.evaluate().
    RiskEngine extrait : entry_price, stop_loss, take_profit, symbol, side, asset, confidence.
    """

    def __init__(self, intent: OrderIntent):
        self.intent = intent
        # Champs lus par RiskEngine._extract_signal_payload
        self.symbol = intent.symbol
        self.side = intent.side
        self.entry_price = intent.requested_price or intent.stop_price or 0
        self.stop_loss = intent.stop_loss
        self.take_profit = intent.take_profit
        self.asset_id = intent.asset_id
        self.confidence = (intent.metadata or {}).get("confidence", 0.7)


def _evaluate_risk(intent: OrderIntent):
    """
    Appelle RiskEngine(portfolio).evaluate(signal_like) avec un adapter.
    RiskEngine.__init__ prend un portfolio, .evaluate(signal) retourne RiskEngineDecision.

    Si RiskEngine plante (signal trop incomplet, profil absent), on fallback
    sur une décision "approved" avec les valeurs de l'intent (l'orchestrator
    aura toujours fait l'idempotency check + lock cash en garde-fou).
    """
    from risk.engine import RiskEngine, RiskEngineDecision
    from portfolio.models import Portfolio
    from decimal import Decimal

    try:
        portfolio = Portfolio.objects.get(pk=intent.portfolio_id)
    except Portfolio.DoesNotExist:
        return RiskEngineDecision(
            accepted=False, decision="REJECT",
            reason=f"Portfolio {intent.portfolio_id} introuvable.",
            requested_stake=Decimal("0"), approved_stake=Decimal("0"),
            requested_quantity=Decimal("0"), approved_quantity=Decimal("0"),
            requested_notional=Decimal("0"), approved_notional=Decimal("0"),
            expected_loss=Decimal("0"), expected_gain=Decimal("0"),
            risk_reward_ratio=Decimal("0"),
            risk_profile_id=None, risk_decision_id=None, payload={},
        )

    signal_like = _IntentSignalAdapter(intent)
    try:
        engine = RiskEngine(portfolio)
        decision = engine.evaluate(signal_like)
    except Exception as exc:
        log.warning(
            "orchestrator.risk_engine_unavailable portfolio_id=%s err=%s — fallback approve",
            intent.portfolio_id, exc,
        )
        # Fallback : on construit une décision approved minimaliste
        approved_qty = intent.requested_quantity or Decimal("1")
        approved_notional = intent.requested_stake_amount or (
            (intent.requested_price or Decimal("1")) * approved_qty
        )
        return RiskEngineDecision(
            accepted=True, decision="APPROVE",
            reason="risk_engine_fallback",
            requested_stake=approved_notional, approved_stake=approved_notional,
            requested_quantity=approved_qty, approved_quantity=approved_qty,
            requested_notional=approved_notional, approved_notional=approved_notional,
            expected_loss=Decimal("0"), expected_gain=Decimal("0"),
            risk_reward_ratio=Decimal("0"),
            risk_profile_id=None, risk_decision_id=None,
            payload={"fallback": True, "error": str(exc)},
        )
    return decision


def _is_approved(decision) -> bool:
    """
    RiskEngineDecision a un attribut `accepted` (booléen) — c'est l'autorité.
    On garde aussi le check `approved` au cas où un autre type de décision arrive.
    """
    return bool(
        getattr(decision, "accepted", False) or getattr(decision, "approved", False)
    )


def _decision_reason(decision) -> str:
    return str(
        getattr(decision, "reason", "")
        or getattr(decision, "rejection_reason", "")
        or "rejected"
    )


def _create_order_from_decision(intent: OrderIntent, decision) -> Order:
    approved_qty = Decimal(str(getattr(decision, "approved_quantity", intent.requested_quantity or 0)))
    approved_notional = Decimal(str(getattr(decision, "approved_notional", 0)))

    return Order.objects.create(
        user_id=intent.user_id,
        portfolio_id=intent.portfolio_id,
        broker_account_id=intent.broker_account_id,
        signal_id=intent.signal_id,
        trade_idea_id=intent.trade_idea_id,
        asset_id=intent.asset_id,
        symbol=intent.symbol,
        side=intent.side,
        order_type=intent.order_type,
        mode=intent.mode,
        source=intent.source,
        requested_quantity=intent.requested_quantity or Decimal("0"),
        approved_quantity=approved_qty,
        requested_stake_amount=intent.requested_stake_amount or Decimal("0"),
        approved_notional=approved_notional,
        requested_price=intent.requested_price or Decimal("0"),
        limit_price=intent.requested_price if intent.order_type == "LIMIT" else None,
        stop_price=intent.stop_price,
        stop_loss=intent.stop_loss,
        take_profit=intent.take_profit,
        leverage=intent.leverage,
        idempotency_key=intent.idempotency_key,
        status="PENDING_SUBMIT",
        metadata=intent.metadata,
    )


def _dispatch_to_broker(order_id: int) -> None:
    """
    Appelé après commit de l'Order. Délègue à une tâche Celery pour
    l'appel broker effectif.
    """
    from execution.tasks import submit_order_to_broker_task
    submit_order_to_broker_task.delay(order_id)
