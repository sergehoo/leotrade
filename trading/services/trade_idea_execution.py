from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation, ROUND_CEILING

from django.db import DatabaseError, transaction
from django.db.transaction import TransactionManagementError

from brokers.models import BrokerConstraint
from brokers.services.base import BrokerConstraintSyncService
from core.realtime import RealtimeBroadcastService
from execution.notifications import TradingNotificationService
from execution.services import ExecutionOrchestrator
from portfolio.services import PortfolioService
from risk.services import (
    PositionSizingService,
    RiskDecisionService,
    RiskGuardService,
)
from trading.models import TradeIdeaFeedback
from trading.services.agents.portfolio_advisor_agent import PortfolioAdvisorAgent

logger = logging.getLogger(__name__)


# class TradeIdeaExecutionService:
#     DEFAULT_MIN_QTY = Decimal("0.00000001")
#     DEFAULT_QTY_STEP = Decimal("0.00000001")
#     DEFAULT_MIN_NOTIONAL = Decimal("0")
#     DEFAULT_LEVERAGE = Decimal("1")
#     MONEY_PRECISION = Decimal("0.01")
#     ZERO = Decimal("0")
#
#     DERIV_DEFAULT_MIN_STAKE = Decimal("1.00")
#     DERIV_SYNTHETIC_PREFIXES = (
#         "R_", "1HZ", "HZ", "JD", "JUMP",
#         "CRASH", "BOOM", "STEP", "VOL",
#     )
#
#     FILLED_STATUSES = {"FILLED", "PARTIALLY_FILLED"}
#     FAILED_STATUSES = {"REJECTED", "FAILED", "CANCELLED", "EXPIRED"}
#     PENDING_STATUSES = {"PENDING", "CREATED", "SUBMITTED", "NEW", "OPEN"}
#
#     @classmethod
#     def _is_deriv_broker(cls, broker_account) -> bool:
#         return str(getattr(broker_account, "broker", "") or "").upper() == "DERIV"
#
#     @classmethod
#     def _is_deriv_symbol(cls, symbol: str) -> bool:
#         symbol = str(symbol or "").upper().strip()
#         return symbol.startswith(cls.DERIV_SYNTHETIC_PREFIXES)
#
#     @classmethod
#     def _build_deriv_sizing(cls, stake_amount: Decimal):
#         """
#         Sizing pour les contrats Deriv (options binaires / multipliers).
#
#         Convention Lyneci pour Deriv :
#           - 1 contrat = 1 unité de position
#           - le ``stake_amount`` est à la fois la mise et le notional
#           - la quantité doit donc rester à 1 (et NON pas égale au stake)
#
#         FIX : on remettait ``quantity = stake_amount`` ce qui faisait que la
#         position ouverte avait notional = stake * buy_price (au lieu de stake)
#         et que ``filled_quantity >= approved_quantity`` ne basculait jamais en
#         FILLED si le broker répondait avec quantity=1.
#         """
#
#         class DerivSizing:
#             requested_stake = stake_amount
#             quantity = Decimal("1")
#             notional = stake_amount
#             leverage = Decimal("1")
#             reason = "Deriv stake-based contract (qty=1, notional=stake)"
#
#         return DerivSizing()
#
#     @staticmethod
#     def _to_decimal(value, field_name: str, allow_none: bool = False) -> Decimal | None:
#         if value is None or value == "":
#             if allow_none:
#                 return None
#             raise ValueError(f"Valeur requise manquante pour {field_name}.")
#
#         try:
#             return Decimal(str(value))
#         except (InvalidOperation, TypeError, ValueError):
#             raise ValueError(f"Valeur invalide pour {field_name}: {value}")
#
#     @classmethod
#     def _money_up(cls, value: Decimal) -> Decimal:
#         try:
#             return value.quantize(cls.MONEY_PRECISION, rounding=ROUND_CEILING)
#         except Exception:
#             return cls.ZERO
#
#     @classmethod
#     def _resolve_constraint(cls, broker_account, symbol: str):
#         constraint = BrokerConstraint.objects.filter(
#             broker=broker_account.broker,
#             symbol=symbol,
#         ).first()
#
#         if constraint:
#             return constraint
#
#         try:
#             return BrokerConstraintSyncService.sync_symbol_constraint(
#                 broker_account=broker_account,
#                 symbol=symbol,
#             )
#         except Exception as exc:
#             logger.warning(
#                 "Sync contrainte broker impossible broker=%s symbol=%s error=%s",
#                 broker_account.broker,
#                 symbol,
#                 exc,
#             )
#             return None
#
#     @classmethod
#     def _estimate_broker_minimum_stake(
#         cls,
#         *,
#         entry_price: Decimal,
#         min_qty: Decimal,
#         min_notional: Decimal,
#     ) -> Decimal:
#         if entry_price <= cls.ZERO:
#             return cls.ZERO
#
#         minimum_required = max(entry_price * min_qty, min_notional, cls.ZERO)
#         return cls._money_up(minimum_required)
#
#     @classmethod
#     def _estimate_risk_minimum_required(
#         cls,
#         *,
#         entry_price: Decimal,
#         stop_loss: Decimal | None,
#         min_qty: Decimal,
#     ) -> Decimal:
#         if entry_price <= cls.ZERO or min_qty <= cls.ZERO:
#             return cls.ZERO
#
#         if stop_loss is None or stop_loss <= cls.ZERO or stop_loss == entry_price:
#             return cls.ZERO
#
#         stop_distance = abs(entry_price - stop_loss)
#
#         if stop_distance <= cls.ZERO:
#             return cls.ZERO
#
#         return cls._money_up(stop_distance * min_qty)
#
#     @staticmethod
#     def _model_allows_value(instance, field_name: str, value: str) -> bool:
#         try:
#             field = instance._meta.get_field(field_name)
#             if not field.choices:
#                 return True
#
#             allowed = {str(choice[0]) for choice in field.choices}
#             return value in allowed
#         except Exception:
#             return True
#
#     @classmethod
#     def _safe_set_idea_status(cls, idea, preferred_status: str) -> str:
#         """
#         Évite les erreurs si le modèle TradeIdea n'a pas encore ORDER_SUBMITTED
#         dans ses choices.
#         """
#         fallback_map = {
#             "ORDER_SUBMITTED": ["ORDER_SUBMITTED", "SUBMITTED", "PENDING", "APPROVED"],
#             "EXECUTED": ["EXECUTED", "FILLED", "COMPLETED"],
#             "FAILED": ["FAILED", "REJECTED", "CANCELLED", "ERROR"],
#         }
#
#         candidates = fallback_map.get(preferred_status, [preferred_status])
#
#         for status in candidates:
#             if cls._model_allows_value(idea, "status", status):
#                 idea.status = status
#                 idea.save(update_fields=["status", "updated_at"])
#                 return status
#
#         idea.status = preferred_status
#         idea.save(update_fields=["status", "updated_at"])
#         return preferred_status
#
#     @classmethod
#     def _idea_status_from_order(cls, order) -> str:
#         order_status = str(getattr(order, "status", "") or "").upper()
#
#         if order_status in cls.FILLED_STATUSES:
#             return "EXECUTED"
#
#         if order_status in cls.FAILED_STATUSES:
#             return "FAILED"
#
#         return "ORDER_SUBMITTED"
#
#     @classmethod
#     def _feedback_outcome_from_order(cls, order) -> str:
#         order_status = str(getattr(order, "status", "") or "").upper()
#
#         if order_status in cls.FILLED_STATUSES:
#             return "OPEN"
#
#         if order_status in cls.FAILED_STATUSES:
#             return "FAILED"
#
#         return "PENDING"
#
#     @classmethod
#     def execute(
#         cls,
#         idea,
#         broker_account,
#         portfolio,
#         stake_amount: Decimal,
#         *,
#         risk_override: bool = False,
#         risk_override_reason: str = "",
#         risk_override_user_id: int | None = None,
#     ):
#         """
#         Lance l'exécution de la TradeIdea.
#
#         Décharge utilisateur (risk_override)
#         ------------------------------------
#         Si l'utilisateur a coché « Je passe outre, j'assume le risque »
#         depuis l'UI, on transmet ``risk_override=True`` au RiskGuardService.
#         Les blocages SOFT (positions max, exposures, drawdown en LIVE…)
#         sont alors franchis et tracés dans ``order.metadata.risk_override``
#         pour audit. Les blocages HARD (kill switch en LIVE, profil qui
#         interdit le live, short interdit) restent bloquants.
#         """
#         notification_data = None
#         broadcast_data = None
#
#         order = None
#         risk_decision = None
#         signal = None
#         sizing = None
#         approval = None
#         constraint = None
#         broker_minimum_stake = cls.ZERO
#         risk_minimum_required = cls.ZERO
#         min_qty = cls.ZERO
#         qty_step = cls.ZERO
#         min_notional = cls.ZERO
#
#         try:
#             with transaction.atomic():
#                 if idea.user_id != portfolio.user_id or idea.user_id != broker_account.user_id:
#                     raise ValueError("Incohérence utilisateur sur l'exécution.")
#
#                 if not idea.signal:
#                     raise ValueError("Signal manquant pour cette TradeIdea.")
#
#                 if not idea.asset:
#                     raise ValueError("Asset manquant pour cette TradeIdea.")
#
#                 if not idea.symbol:
#                     raise ValueError("Symbole manquant pour cette TradeIdea.")
#
#                 stake_amount = cls._to_decimal(stake_amount, "stake_amount")
#
#                 if stake_amount <= cls.ZERO:
#                     raise ValueError("Le montant d'engagement doit être supérieur à zéro.")
#
#                 entry_price = cls._to_decimal(idea.entry_price, "entry_price")
#                 stop_loss = cls._to_decimal(idea.stop_loss, "stop_loss", allow_none=True)
#                 take_profit = cls._to_decimal(idea.take_profit, "take_profit", allow_none=True)
#                 portfolio = PortfolioService.refresh_portfolio_metrics(portfolio)
#                 portfolio.refresh_from_db()
#                 is_deriv = cls._is_deriv_broker(broker_account)
#
#                 if not is_deriv:
#                     advice = PortfolioAdvisorAgent.advise(portfolio)
#
#                     if advice.action in ["BLOCK_NEW_POSITIONS", "CLOSE_WEAK_POSITIONS"]:
#                         reason = getattr(advice, "reason", "") or getattr(advice, "summary","") or "Portefeuille bloqué."
#                         raise ValueError(f"Exécution bloquée: {reason}")
#
#                 signal = idea.signal
#                 side = "BUY" if idea.direction in ["BUY", "CALL"] else "SELL"
#                 risk_profile = RiskGuardService.get_default_profile(portfolio)
#
#                 is_deriv = cls._is_deriv_broker(broker_account)
#
#                 if is_deriv:
#                     constraint = None
#                     min_qty = cls.ZERO
#                     qty_step = cls.ZERO
#                     min_notional = cls.ZERO
#                     broker_minimum_stake = cls.DERIV_DEFAULT_MIN_STAKE
#                     risk_minimum_required = cls.ZERO
#
#                     if stake_amount < broker_minimum_stake:
#                         raise ValueError(
#                             f"Exécution impossible pour {idea.symbol}. "
#                             f"Minimum Deriv requis : {broker_minimum_stake}."
#                         )
#
#                     sizing = cls._build_deriv_sizing(stake_amount)
#
#                 else:
#                     constraint = cls._resolve_constraint(broker_account, idea.symbol)
#
#                     min_qty = cls._to_decimal(
#                         getattr(constraint, "min_qty", None) or cls.DEFAULT_MIN_QTY,
#                         "min_qty",
#                     )
#                     qty_step = cls._to_decimal(
#                         getattr(constraint, "qty_step", None) or cls.DEFAULT_QTY_STEP,
#                         "qty_step",
#                     )
#                     min_notional = cls._to_decimal(
#                         getattr(constraint, "min_notional", None) or cls.DEFAULT_MIN_NOTIONAL,
#                         "min_notional",
#                     )
#
#                     broker_minimum_stake = cls._estimate_broker_minimum_stake(
#                         entry_price=entry_price,
#                         min_qty=min_qty,
#                         min_notional=min_notional,
#                     )
#
#                     risk_minimum_required = cls._estimate_risk_minimum_required(
#                         entry_price=entry_price,
#                         stop_loss=stop_loss,
#                         min_qty=min_qty,
#                     )
#
#                     try:
#                         sizing = PositionSizingService.compute(
#                             portfolio=portfolio,
#                             risk_profile=risk_profile,
#                             entry_price=entry_price,
#                             stop_loss=stop_loss,
#                             requested_stake=stake_amount,
#                             min_qty=min_qty,
#                             qty_step=qty_step,
#                             min_notional=min_notional,
#                             leverage=cls.DEFAULT_LEVERAGE,
#                         )
#                     except ValueError as exc:
#                         message = str(exc)
#                         lowered = message.lower()
#
#                         if (
#                             "minimum broker" in lowered
#                             or "inférieure au minimum" in lowered
#                             or "quantité inférieure" in lowered
#                         ):
#                             raise ValueError(
#                                 f"Exécution impossible pour {idea.symbol}. "
#                                 f"Minimum broker théorique : {broker_minimum_stake}. "
#                                 f"Risque minimal requis pour atteindre {min_qty} unité(s) : {risk_minimum_required}. "
#                                 f"Contraintes broker : min_qty={min_qty}, qty_step={qty_step}, min_notional={min_notional}. "
#                                 f"Détail du blocage : {message}"
#                             )
#
#                         raise
#
#                 approval = RiskGuardService.validate_trade(
#                     portfolio=portfolio,
#                     symbol=idea.symbol,
#                     asset=idea.asset,
#                     side=side,
#                     requested_stake=sizing.requested_stake,
#                     approved_quantity=sizing.quantity,
#                     approved_notional=sizing.notional,
#                     entry_price=entry_price,
#                     stop_loss=stop_loss,
#                     take_profit=take_profit,
#                     confidence=cls._to_decimal(
#                         getattr(idea, "confidence_score", 0),
#                         "confidence_score",
#                     ),
#                     signal=signal,
#                     trade_idea=idea,
#                     risk_override=risk_override,
#                     risk_override_reason=risk_override_reason,
#                     risk_override_user_id=risk_override_user_id,
#                 )
#
#                 risk_decision = RiskDecisionService.persist_decision(
#                     portfolio=portfolio,
#                     risk_profile=risk_profile,
#                     symbol=idea.symbol,
#                     asset_class=getattr(idea.asset, "asset_class", None),
#                     side=side,
#                     requested_stake=sizing.requested_stake,
#                     approved_result=approval,
#                     requested_quantity=sizing.quantity,
#                     requested_notional=sizing.notional,
#                     signal=signal,
#                     trade_idea=idea,
#                 )
#
#                 if approval.decision in {"BLOCK", "REJECT"}:
#                     raise ValueError(
#                         approval.blocking_reason or "Trade refusé par le risk engine."
#                     )
#
#                 order = ExecutionOrchestrator.create_order(
#                     user=idea.user,
#                     portfolio=portfolio,
#                     broker_account=broker_account,
#                     symbol=idea.symbol,
#                     side=side,
#                     approved_quantity=approval.approved_quantity,
#                     requested_stake_amount=approval.approved_stake,
#                     approved_notional=approval.approved_notional,
#                     requested_price=entry_price,
#                     signal=signal,
#                     trade_idea=idea,
#                     asset=idea.asset,
#                     order_type="MARKET",
#                     source="AI_ASSISTED",
#                     stop_loss=stop_loss,
#                     take_profit=take_profit,
#                     leverage=sizing.leverage,
#                     metadata={
#                         "trade_idea_id": idea.id,
#                         "confidence_score": str(getattr(idea, "confidence_score", 0)),
#                         "overall_score": str(getattr(idea, "overall_score", 0)),
#                         "risk_decision_id": risk_decision.id,
#                         "broker_minimum_stake": str(broker_minimum_stake),
#                         "risk_minimum_required": str(risk_minimum_required),
#                         "min_qty": str(min_qty),
#                         "qty_step": str(qty_step),
#                         "min_notional": str(min_notional),
#                         "sizing_reason": getattr(sizing, "reason", ""),
#                         "requested_stake": str(stake_amount),
#                         # Trace de la décharge utilisateur (audit) — utile
#                         # pour les logs et l'export comptable.
#                         "risk_override": bool(risk_override),
#                         "risk_override_reason": risk_override_reason or "",
#                         "risk_override_user_id": risk_override_user_id,
#                     },
#                 )
#
#                 risk_decision.order = order
#                 risk_decision.save(update_fields=["order", "updated_at"])
#
#                 cls._safe_set_idea_status(idea, "ORDER_SUBMITTED")
#
#             try:
#                 ExecutionOrchestrator.submit_order(order)
#                 order.refresh_from_db()
#             except Exception as exc:
#                 logger.exception(
#                     "Erreur pendant la soumission broker TradeIdea id=%s order_id=%s symbol=%s error=%s",
#                     getattr(idea, "id", None),
#                     getattr(order, "id", None),
#                     getattr(idea, "symbol", None),
#                     exc,
#                 )
#
#                 try:
#                     order.status = "FAILED"
#                     order.metadata = {
#                         **(order.metadata or {}),
#                         "submit_error": str(exc),
#                     }
#                     order.save(update_fields=["status", "metadata", "updated_at"])
#                 except Exception:
#                     logger.exception(
#                         "Impossible de marquer l'ordre comme FAILED order_id=%s",
#                         getattr(order, "id", None),
#                     )
#
#                 cls._safe_set_idea_status(idea, "FAILED")
#                 raise ValueError(f"Soumission broker échouée: {exc}")
#
#             final_idea_status = cls._idea_status_from_order(order)
#             saved_idea_status = cls._safe_set_idea_status(idea, final_idea_status)
#
#             TradeIdeaFeedback.objects.update_or_create(
#                 idea=idea,
#                 defaults={
#                     "signal": signal,
#                     "order_id": str(order.id),
#                     "execution_status": order.status,
#                     "outcome": cls._feedback_outcome_from_order(order),
#                     "notes": (
#                         f"Trade IA soumis via {broker_account.broker}/{broker_account.mode}. "
#                         f"Statut broker: {order.status}."
#                     ),
#                     "learning_payload": {
#                         "requested_stake": str(sizing.requested_stake),
#                         "sizing_notional": str(sizing.notional),
#                         "approved_stake": str(approval.approved_stake),
#                         "approved_notional": str(approval.approved_notional),
#                         "approved_quantity": str(approval.approved_quantity),
#                         "risk_decision_id": risk_decision.id,
#                         "order_id": order.id,
#                         "order_status": order.status,
#                         "idea_status": saved_idea_status,
#                         "broker_minimum_stake": str(broker_minimum_stake),
#                         "risk_minimum_required": str(risk_minimum_required),
#                         "min_qty": str(min_qty),
#                         "qty_step": str(qty_step),
#                         "min_notional": str(min_notional),
#                         "sizing_reason": getattr(sizing, "reason", ""),
#                     },
#                 },
#             )
#
#             if order.status in cls.FILLED_STATUSES:
#                 message = f"Trade IA exécuté sur {idea.symbol}"
#                 kind = "ai_trade_executed"
#             elif order.status in cls.FAILED_STATUSES:
#                 message = f"Trade IA refusé ou échoué sur {idea.symbol}"
#                 kind = "ai_trade_failed"
#             else:
#                 message = f"Ordre IA soumis sur {idea.symbol}"
#                 kind = "ai_trade_submitted"
#
#             notification_data = {
#                 "user_id": idea.user_id,
#                 "message": message,
#                 "payload": {
#                     "trade_idea_id": idea.id,
#                     "symbol": idea.symbol,
#                     "order_id": order.id,
#                     "order_status": order.status,
#                     "idea_status": saved_idea_status,
#                 },
#             }
#
#             broadcast_data = {
#                 "user_id": idea.user_id,
#                 "payload": {
#                     "kind": kind,
#                     "trade_idea_id": idea.id,
#                     "symbol": idea.symbol,
#                     "order_id": order.id,
#                     "status": order.status,
#                     "idea_status": saved_idea_status,
#                 },
#             }
#
#             result = {
#                 "idea": idea,
#                 "signal": signal,
#                 "order": order,
#                 "risk_decision": risk_decision,
#                 "sizing": sizing,
#                 "approval": approval,
#                 "constraint": constraint,
#                 "broker_minimum_stake": broker_minimum_stake,
#                 "risk_minimum_required": risk_minimum_required,
#             }
#
#         except (DatabaseError, TransactionManagementError):
#             logger.exception(
#                 "Erreur DB/transaction pendant l'exécution de TradeIdea id=%s symbol=%s",
#                 getattr(idea, "id", None),
#                 getattr(idea, "symbol", None),
#             )
#             raise
#
#         if notification_data:
#             TradingNotificationService.notify_success(
#                 user_id=notification_data["user_id"],
#                 message=notification_data["message"],
#                 payload=notification_data["payload"],
#             )
#
#         if broadcast_data:
#             RealtimeBroadcastService.broadcast_dashboard_update(
#                 user_id=broadcast_data["user_id"],
#                 payload=broadcast_data["payload"],
#             )
#
#         return result

class TradeIdeaExecutionService:
    DEFAULT_MIN_QTY = Decimal("0.00000001")
    DEFAULT_QTY_STEP = Decimal("0.00000001")
    DEFAULT_MIN_NOTIONAL = Decimal("0")
    DEFAULT_LEVERAGE = Decimal("1")
    MONEY_PRECISION = Decimal("0.01")
    ZERO = Decimal("0")

    DERIV_DEFAULT_MIN_STAKE = Decimal("1.00")
    DERIV_SYNTHETIC_PREFIXES = (
        "R_", "1HZ", "HZ", "JD", "JUMP",
        "CRASH", "BOOM", "STEP", "VOL",
    )

    FILLED_STATUSES = {"FILLED", "PARTIALLY_FILLED"}
    FAILED_STATUSES = {"REJECTED", "FAILED", "CANCELLED", "EXPIRED"}
    PENDING_STATUSES = {"PENDING", "CREATED", "SUBMITTED", "NEW", "OPEN"}

    @classmethod
    def _is_deriv_broker(cls, broker_account) -> bool:
        return str(getattr(broker_account, "broker", "") or "").upper() == "DERIV"

    @classmethod
    def _is_deriv_symbol(cls, symbol: str) -> bool:
        symbol = str(symbol or "").upper().strip()
        return symbol.startswith(cls.DERIV_SYNTHETIC_PREFIXES)

    @classmethod
    def _is_deriv_multiplier_symbol(cls, symbol: str) -> bool:
        symbol = str(symbol or "").upper().strip()
        return symbol.startswith(("BOOM", "CRASH"))

    @classmethod
    def _build_deriv_sizing(cls, stake_amount: Decimal):
        class DerivSizing:
            requested_stake = stake_amount
            quantity = Decimal("1")
            notional = stake_amount
            leverage = Decimal("1")
            reason = "Deriv stake-based contract (qty=1, notional=stake)"

        return DerivSizing()

    @staticmethod
    def _to_decimal(value, field_name: str, allow_none: bool = False) -> Decimal | None:
        if value is None or value == "":
            if allow_none:
                return None
            raise ValueError(f"Valeur requise manquante pour {field_name}.")

        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError(f"Valeur invalide pour {field_name}: {value}")

    @staticmethod
    def _to_int(value, default=None):
        try:
            if value is None or value == "":
                return default
            return int(value)
        except Exception:
            return default

    @classmethod
    def _money_up(cls, value: Decimal) -> Decimal:
        try:
            return value.quantize(cls.MONEY_PRECISION, rounding=ROUND_CEILING)
        except Exception:
            return cls.ZERO

    @classmethod
    def _resolve_constraint(cls, broker_account, symbol: str):
        constraint = BrokerConstraint.objects.filter(
            broker=broker_account.broker,
            symbol=symbol,
        ).first()

        if constraint:
            return constraint

        try:
            return BrokerConstraintSyncService.sync_symbol_constraint(
                broker_account=broker_account,
                symbol=symbol,
            )
        except Exception as exc:
            logger.warning(
                "Sync contrainte broker impossible broker=%s symbol=%s error=%s",
                broker_account.broker,
                symbol,
                exc,
            )
            return None

    @classmethod
    def _estimate_broker_minimum_stake(
        cls,
        *,
        entry_price: Decimal,
        min_qty: Decimal,
        min_notional: Decimal,
    ) -> Decimal:
        if entry_price <= cls.ZERO:
            return cls.ZERO

        minimum_required = max(entry_price * min_qty, min_notional, cls.ZERO)
        return cls._money_up(minimum_required)

    @classmethod
    def _estimate_risk_minimum_required(
        cls,
        *,
        entry_price: Decimal,
        stop_loss: Decimal | None,
        min_qty: Decimal,
    ) -> Decimal:
        if entry_price <= cls.ZERO or min_qty <= cls.ZERO:
            return cls.ZERO

        if stop_loss is None or stop_loss <= cls.ZERO or stop_loss == entry_price:
            return cls.ZERO

        stop_distance = abs(entry_price - stop_loss)

        if stop_distance <= cls.ZERO:
            return cls.ZERO

        return cls._money_up(stop_distance * min_qty)

    @staticmethod
    def _model_allows_value(instance, field_name: str, value: str) -> bool:
        try:
            field = instance._meta.get_field(field_name)
            if not field.choices:
                return True

            allowed = {str(choice[0]) for choice in field.choices}
            return value in allowed
        except Exception:
            return True

    @classmethod
    def _safe_set_idea_status(cls, idea, preferred_status: str) -> str:
        fallback_map = {
            "ORDER_SUBMITTED": ["ORDER_SUBMITTED", "SUBMITTED", "PENDING", "APPROVED"],
            "EXECUTED": ["EXECUTED", "FILLED", "COMPLETED"],
            "FAILED": ["FAILED", "REJECTED", "CANCELLED", "ERROR"],
        }

        candidates = fallback_map.get(preferred_status, [preferred_status])

        for status in candidates:
            if cls._model_allows_value(idea, "status", status):
                idea.status = status
                idea.save(update_fields=["status", "updated_at"])
                return status

        idea.status = preferred_status
        idea.save(update_fields=["status", "updated_at"])
        return preferred_status

    @classmethod
    def _idea_status_from_order(cls, order) -> str:
        order_status = str(getattr(order, "status", "") or "").upper()

        if order_status in cls.FILLED_STATUSES:
            return "EXECUTED"

        if order_status in cls.FAILED_STATUSES:
            return "FAILED"

        return "ORDER_SUBMITTED"

    @classmethod
    def _feedback_outcome_from_order(cls, order) -> str:
        order_status = str(getattr(order, "status", "") or "").upper()

        if order_status in cls.FILLED_STATUSES:
            return "OPEN"

        if order_status in cls.FAILED_STATUSES:
            return "FAILED"

        return "PENDING"

    @classmethod
    def _build_deriv_order_metadata(cls, idea, signal) -> dict:
        metadata = {}

        signal_metadata = getattr(signal, "metadata", None) or {}

        duration = cls._to_int(signal_metadata.get("duration"), 5)
        duration_unit = signal_metadata.get("duration_unit") or "t"
        multiplier = cls._to_int(signal_metadata.get("multiplier"), 100)

        if cls._is_deriv_multiplier_symbol(idea.symbol):
            metadata.update({
                "deriv_contract_family": "MULTIPLIER",
                "multiplier": multiplier,
                "duration": None,
                "duration_unit": None,
            })
        else:
            metadata.update({
                "deriv_contract_family": "VANILLA",
                "duration": duration,
                "duration_unit": duration_unit,
                "multiplier": None,
            })

        return metadata

    @classmethod
    def execute(
        cls,
        idea,
        broker_account,
        portfolio,
        stake_amount: Decimal,
        *,
        risk_override: bool = False,
        risk_override_reason: str = "",
        risk_override_user_id: int | None = None,
        risk_override_ip: str = "",
        risk_override_user_agent: str = "",
    ):
        notification_data = None
        broadcast_data = None

        order = None
        risk_decision = None
        signal = None
        sizing = None
        approval = None
        constraint = None
        broker_minimum_stake = cls.ZERO
        risk_minimum_required = cls.ZERO
        min_qty = cls.ZERO
        qty_step = cls.ZERO
        min_notional = cls.ZERO
        result = None

        try:
            with transaction.atomic():
                if idea.user_id != portfolio.user_id or idea.user_id != broker_account.user_id:
                    raise ValueError("Incohérence utilisateur sur l'exécution.")

                if getattr(portfolio, "broker_account_id", None) and portfolio.broker_account_id != broker_account.id:
                    raise ValueError(
                        "Le portefeuille sélectionné n'est pas lié au broker choisi."
                    )

                if not idea.signal:
                    raise ValueError("Signal manquant pour cette TradeIdea.")

                if not idea.asset:
                    raise ValueError("Asset manquant pour cette TradeIdea.")

                if not idea.symbol:
                    raise ValueError("Symbole manquant pour cette TradeIdea.")

                stake_amount = cls._to_decimal(stake_amount, "stake_amount")

                if stake_amount <= cls.ZERO:
                    raise ValueError("Le montant d'engagement doit être supérieur à zéro.")

                entry_price = cls._to_decimal(idea.entry_price, "entry_price")
                stop_loss = cls._to_decimal(idea.stop_loss, "stop_loss", allow_none=True)
                take_profit = cls._to_decimal(idea.take_profit, "take_profit", allow_none=True)

                portfolio = PortfolioService.refresh_portfolio_metrics(portfolio)
                portfolio.refresh_from_db()

                is_deriv = cls._is_deriv_broker(broker_account)

                if not is_deriv:
                    advice = PortfolioAdvisorAgent.advise(portfolio)

                    if advice.action in ["BLOCK_NEW_POSITIONS", "CLOSE_WEAK_POSITIONS"]:
                        reason = (
                            getattr(advice, "reason", "")
                            or getattr(advice, "summary", "")
                            or "Portefeuille bloqué."
                        )
                        raise ValueError(f"Exécution bloquée: {reason}")

                signal = idea.signal
                if signal.status not in {"APPROVED", "QUEUED"}:
                    from strategies.services.signal_review import SignalReviewService

                    signal = SignalReviewService.approve(
                        signal_id=signal.id,
                        user=idea.user,
                    )
                side = "BUY" if idea.direction in ["BUY", "CALL"] else "SELL"
                risk_profile = RiskGuardService.get_default_profile(portfolio)

                if is_deriv:
                    constraint = None
                    min_qty = cls.ZERO
                    qty_step = cls.ZERO
                    min_notional = cls.ZERO
                    broker_minimum_stake = cls.DERIV_DEFAULT_MIN_STAKE
                    risk_minimum_required = cls.ZERO

                    if stake_amount < broker_minimum_stake:
                        raise ValueError(
                            f"Exécution impossible pour {idea.symbol}. "
                            f"Minimum Deriv requis : {broker_minimum_stake}."
                        )

                    sizing = cls._build_deriv_sizing(stake_amount)

                else:
                    constraint = cls._resolve_constraint(broker_account, idea.symbol)

                    min_qty = cls._to_decimal(
                        getattr(constraint, "min_qty", None) or cls.DEFAULT_MIN_QTY,
                        "min_qty",
                    )
                    qty_step = cls._to_decimal(
                        getattr(constraint, "qty_step", None) or cls.DEFAULT_QTY_STEP,
                        "qty_step",
                    )
                    min_notional = cls._to_decimal(
                        getattr(constraint, "min_notional", None) or cls.DEFAULT_MIN_NOTIONAL,
                        "min_notional",
                    )

                    broker_minimum_stake = cls._estimate_broker_minimum_stake(
                        entry_price=entry_price,
                        min_qty=min_qty,
                        min_notional=min_notional,
                    )

                    risk_minimum_required = cls._estimate_risk_minimum_required(
                        entry_price=entry_price,
                        stop_loss=stop_loss,
                        min_qty=min_qty,
                    )

                    try:
                        sizing = PositionSizingService.compute(
                            portfolio=portfolio,
                            risk_profile=risk_profile,
                            entry_price=entry_price,
                            stop_loss=stop_loss,
                            requested_stake=stake_amount,
                            min_qty=min_qty,
                            qty_step=qty_step,
                            min_notional=min_notional,
                            leverage=cls.DEFAULT_LEVERAGE,
                        )
                    except ValueError as exc:
                        message = str(exc)
                        lowered = message.lower()

                        if (
                            "minimum broker" in lowered
                            or "inférieure au minimum" in lowered
                            or "quantité inférieure" in lowered
                        ):
                            raise ValueError(
                                f"Exécution impossible pour {idea.symbol}. "
                                f"Minimum broker théorique : {broker_minimum_stake}. "
                                f"Risque minimal requis pour atteindre {min_qty} unité(s) : {risk_minimum_required}. "
                                f"Contraintes broker : min_qty={min_qty}, qty_step={qty_step}, min_notional={min_notional}. "
                                f"Détail du blocage : {message}"
                            )

                        raise

                approval = RiskGuardService.validate_trade(
                    portfolio=portfolio,
                    symbol=idea.symbol,
                    asset=idea.asset,
                    side=side,
                    requested_stake=sizing.requested_stake,
                    approved_quantity=sizing.quantity,
                    approved_notional=sizing.notional,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    confidence=cls._to_decimal(
                        getattr(idea, "confidence_score", 0),
                        "confidence_score",
                    ),
                    signal=signal,
                    trade_idea=idea,
                    risk_override=risk_override,
                    risk_override_reason=risk_override_reason,
                    risk_override_user_id=risk_override_user_id,
                    risk_override_ip=risk_override_ip,
                    risk_override_user_agent=risk_override_user_agent,
                )

                risk_decision = RiskDecisionService.persist_decision(
                    portfolio=portfolio,
                    risk_profile=risk_profile,
                    symbol=idea.symbol,
                    asset_class=getattr(idea.asset, "asset_class", None),
                    side=side,
                    requested_stake=sizing.requested_stake,
                    approved_result=approval,
                    requested_quantity=sizing.quantity,
                    requested_notional=sizing.notional,
                    signal=signal,
                    trade_idea=idea,
                )

                if approval.decision in {"BLOCK", "REJECT"}:
                    raise ValueError(
                        approval.blocking_reason or "Trade refusé par le risk engine."
                    )

                deriv_metadata = {}
                if is_deriv:
                    deriv_metadata = cls._build_deriv_order_metadata(idea, signal)

                order_metadata = {
                    "trade_idea_id": idea.id,
                    "confidence_score": str(getattr(idea, "confidence_score", 0)),
                    "overall_score": str(getattr(idea, "overall_score", 0)),
                    "risk_decision_id": risk_decision.id,
                    "broker_minimum_stake": str(broker_minimum_stake),
                    "risk_minimum_required": str(risk_minimum_required),
                    "min_qty": str(min_qty),
                    "qty_step": str(qty_step),
                    "min_notional": str(min_notional),
                    "sizing_reason": getattr(sizing, "reason", ""),
                    "requested_stake": str(stake_amount),
                    "risk_override": bool(risk_override),
                    "risk_override_reason": risk_override_reason or "",
                    "risk_override_user_id": risk_override_user_id,
                    **deriv_metadata,
                }

                order = ExecutionOrchestrator.create_order(
                    user=idea.user,
                    portfolio=portfolio,
                    broker_account=broker_account,
                    symbol=idea.symbol,
                    side=side,
                    approved_quantity=approval.approved_quantity,
                    requested_stake_amount=approval.approved_stake,
                    approved_notional=approval.approved_notional,
                    requested_price=entry_price,
                    signal=signal,
                    trade_idea=idea,
                    asset=idea.asset,
                    order_type="MARKET",
                    source="AI_ASSISTED",
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    leverage=sizing.leverage,
                    metadata=order_metadata,
                )

                risk_decision.order = order
                risk_decision.save(update_fields=["order", "updated_at"])

                cls._safe_set_idea_status(idea, "ORDER_SUBMITTED")

            try:
                ExecutionOrchestrator.submit_order(order)
                order.refresh_from_db()
            except Exception as exc:
                logger.exception(
                    "Erreur pendant la soumission broker TradeIdea id=%s order_id=%s symbol=%s error=%s",
                    getattr(idea, "id", None),
                    getattr(order, "id", None),
                    getattr(idea, "symbol", None),
                    exc,
                )

                try:
                    order.status = "FAILED"
                    order.metadata = {
                        **(order.metadata or {}),
                        "submit_error": str(exc),
                    }
                    order.save(update_fields=["status", "metadata", "updated_at"])
                except Exception:
                    logger.exception(
                        "Impossible de marquer l'ordre comme FAILED order_id=%s",
                        getattr(order, "id", None),
                    )

                cls._safe_set_idea_status(idea, "FAILED")
                raise ValueError(f"Soumission broker échouée: {exc}")

            final_idea_status = cls._idea_status_from_order(order)
            saved_idea_status = cls._safe_set_idea_status(idea, final_idea_status)

            TradeIdeaFeedback.objects.update_or_create(
                idea=idea,
                defaults={
                    "signal": signal,
                    "order_id": str(order.id),
                    "execution_status": order.status,
                    "outcome": cls._feedback_outcome_from_order(order),
                    "notes": (
                        f"Trade IA soumis via {broker_account.broker}/{broker_account.mode}. "
                        f"Statut broker: {order.status}."
                    ),
                    "learning_payload": {
                        "requested_stake": str(sizing.requested_stake),
                        "sizing_notional": str(sizing.notional),
                        "approved_stake": str(approval.approved_stake),
                        "approved_notional": str(approval.approved_notional),
                        "approved_quantity": str(approval.approved_quantity),
                        "risk_decision_id": risk_decision.id,
                        "order_id": order.id,
                        "order_status": order.status,
                        "idea_status": saved_idea_status,
                        "broker_minimum_stake": str(broker_minimum_stake),
                        "risk_minimum_required": str(risk_minimum_required),
                        "min_qty": str(min_qty),
                        "qty_step": str(qty_step),
                        "min_notional": str(min_notional),
                        "sizing_reason": getattr(sizing, "reason", ""),
                        "order_metadata": order.metadata or {},
                    },
                },
            )

            if order.status in cls.FILLED_STATUSES:
                message = f"Trade IA exécuté sur {idea.symbol}"
                kind = "ai_trade_executed"
            elif order.status in cls.FAILED_STATUSES:
                message = f"Trade IA refusé ou échoué sur {idea.symbol}"
                kind = "ai_trade_failed"
            else:
                message = f"Ordre IA soumis sur {idea.symbol}"
                kind = "ai_trade_submitted"

            notification_data = {
                "user_id": idea.user_id,
                "message": message,
                "payload": {
                    "trade_idea_id": idea.id,
                    "symbol": idea.symbol,
                    "order_id": order.id,
                    "order_status": order.status,
                    "idea_status": saved_idea_status,
                },
            }

            broadcast_data = {
                "user_id": idea.user_id,
                "payload": {
                    "kind": kind,
                    "trade_idea_id": idea.id,
                    "symbol": idea.symbol,
                    "order_id": order.id,
                    "status": order.status,
                    "idea_status": saved_idea_status,
                },
            }

            result = {
                "idea": idea,
                "signal": signal,
                "order": order,
                "risk_decision": risk_decision,
                "sizing": sizing,
                "approval": approval,
                "constraint": constraint,
                "broker_minimum_stake": broker_minimum_stake,
                "risk_minimum_required": risk_minimum_required,
            }

        except (DatabaseError, TransactionManagementError):
            logger.exception(
                "Erreur DB/transaction pendant l'exécution de TradeIdea id=%s symbol=%s",
                getattr(idea, "id", None),
                getattr(idea, "symbol", None),
            )
            raise

        if notification_data:
            TradingNotificationService.notify_success(
                user_id=notification_data["user_id"],
                message=notification_data["message"],
                payload=notification_data["payload"],
            )

        if broadcast_data:
            RealtimeBroadcastService.broadcast_dashboard_update(
                user_id=broadcast_data["user_id"],
                payload=broadcast_data["payload"],
            )

        return result
