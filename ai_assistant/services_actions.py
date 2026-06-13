"""
Couche transactionnelle des actions de l'assistant.

- AssistantActionService        : crée les AssistantActionRequest (résumé +
                                  analyse risque), jamais d'exécution directe.
- AssistantConfirmationService  : confirme (token), impose la DOUBLE
                                  confirmation en LIVE, annule, expire.
- AssistantTradingCommandService: exécute une demande CONFIRMÉE via les
                                  services backend existants UNIQUEMENT
                                  (orchestrateur, risk engine, brokers) —
                                  l'assistant ne parle jamais au broker.

Chaque exécution : journalisée (DecisionAudit / ExecutionEvent via les
services appelés) + notifiée (email + in-app via le module notifications).
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from .models import AssistantActionRequest

log = logging.getLogger("leotrade.ai_assistant.actions")

REQUEST_TTL_MINUTES = 10


class AssistantActionService:
    @staticmethod
    def create_request(*, user, conversation, intent: str, action_type: str,
                       summary: str, target_type: str = "", target_id=None,
                       mode: str = "PAPER", risk_summary: dict | None = None,
                       payload: dict | None = None,
                       message=None) -> AssistantActionRequest:
        return AssistantActionRequest.objects.create(
            user=user,
            conversation=conversation,
            message=message,
            intent=intent,
            action_type=action_type,
            status=AssistantActionRequest.STATUS_WAITING,
            target_type=target_type,
            target_id=target_id,
            mode=mode,
            requires_double_confirmation=(mode == "LIVE"),
            summary=summary,
            risk_summary=risk_summary or {},
            payload=payload or {},
            confirmation_token=secrets.token_urlsafe(32),
            expires_at=timezone.now() + timedelta(minutes=REQUEST_TTL_MINUTES),
        )

    @staticmethod
    def latest_pending(user, conversation=None) -> AssistantActionRequest | None:
        qs = AssistantActionRequest.objects.filter(
            user=user,
            status__in=[
                AssistantActionRequest.STATUS_WAITING,
                AssistantActionRequest.STATUS_CONFIRMED,
            ],
            expires_at__gt=timezone.now(),
        )
        if conversation is not None:
            qs = qs.filter(conversation=conversation)
        return qs.order_by("-created_at").first()

    @staticmethod
    def serialize(request: AssistantActionRequest) -> dict:
        return {
            "id": request.id,
            "intent": request.intent,
            "action_type": request.action_type,
            "status": request.status,
            "mode": request.mode,
            "requires_double_confirmation": request.requires_double_confirmation,
            "confirmations_received": request.confirmations_received,
            "summary": request.summary,
            "risk_summary": request.risk_summary,
            "target_type": request.target_type,
            "target_id": request.target_id,
            "expires_at": request.expires_at.isoformat(),
            "result": request.result,
            "error_message": request.error_message,
        }


class AssistantConfirmationService:
    @classmethod
    def confirm(cls, user, request_id: int, token: str | None = None) -> dict:
        """Confirme une demande. LIVE = deux confirmations distinctes.
        Retourne {ok, status, request, message, executed?}."""
        request = AssistantActionRequest.objects.filter(
            pk=request_id, user=user,
        ).first()
        if request is None:
            return {"ok": False, "message": "Demande introuvable.", "request": None}
        if token and request.confirmation_token != token:
            return {"ok": False, "message": "Jeton de confirmation invalide.",
                    "request": request}
        if request.is_expired and request.status in (
            AssistantActionRequest.STATUS_WAITING,
            AssistantActionRequest.STATUS_CONFIRMED,
        ):
            request.status = AssistantActionRequest.STATUS_EXPIRED
            request.save(update_fields=["status", "updated_at"])
            return {"ok": False, "message": "Demande expirée — relance la préparation.",
                    "request": request}
        if not request.is_actionable:
            return {"ok": False,
                    "message": f"Demande non confirmable (statut {request.status}).",
                    "request": request}

        request.confirmations_received += 1

        # ── DOUBLE confirmation obligatoire en LIVE ──────────────────────
        if (request.requires_double_confirmation
                and request.confirmations_received < 2):
            request.status = AssistantActionRequest.STATUS_CONFIRMED
            request.save(update_fields=["confirmations_received", "status", "updated_at"])
            return {
                "ok": True, "status": request.status, "request": request,
                "executed": False,
                "message": (
                    "⚠ MODE LIVE — argent réel. Première confirmation reçue. "
                    "Confirme une SECONDE fois pour exécuter réellement."
                ),
            }

        request.status = AssistantActionRequest.STATUS_CONFIRMED
        request.save(update_fields=["confirmations_received", "status", "updated_at"])

        # Exécution via les services backend
        result = AssistantTradingCommandService.execute(request)
        return {
            "ok": result.get("ok", False),
            "status": request.status,
            "request": request,
            "executed": True,
            "message": result.get("message", ""),
        }

    @staticmethod
    def cancel(user, request_id: int) -> dict:
        request = AssistantActionRequest.objects.filter(pk=request_id, user=user).first()
        if request is None:
            return {"ok": False, "message": "Demande introuvable.", "request": None}
        if request.status in (
            AssistantActionRequest.STATUS_EXECUTED,
            AssistantActionRequest.STATUS_CANCELLED,
        ):
            return {"ok": False, "message": f"Déjà {request.get_status_display().lower()}.",
                    "request": request}
        request.status = AssistantActionRequest.STATUS_CANCELLED
        request.save(update_fields=["status", "updated_at"])
        return {"ok": True, "message": "Action annulée — rien n'a été exécuté.",
                "request": request}


class AssistantTradingCommandService:
    """Exécuteurs par action_type. Tout passe par les services Django
    existants ; aucune action broker directe ici."""

    @classmethod
    def execute(cls, request: AssistantActionRequest) -> dict:
        handler = getattr(cls, f"_exec_{request.action_type.lower()}", None)
        if handler is None:
            return cls._fail(request, f"Action non supportée : {request.action_type}")
        try:
            result = handler(request)
        except Exception as exc:
            log.exception("assistant.action_failed request=%s", request.id)
            return cls._fail(request, str(exc)[:500])

        request.status = (
            AssistantActionRequest.STATUS_EXECUTED if result.get("ok")
            else AssistantActionRequest.STATUS_FAILED
        )
        request.result = result.get("data", {})
        request.error_message = "" if result.get("ok") else result.get("message", "")
        request.executed_at = timezone.now()
        request.save(update_fields=["status", "result", "error_message",
                                    "executed_at", "updated_at"])

        cls._notify(request, result)
        return result

    # ------------------------------------------------------------------
    @staticmethod
    def _fail(request, message: str) -> dict:
        request.status = AssistantActionRequest.STATUS_FAILED
        request.error_message = message[:2000]
        request.save(update_fields=["status", "error_message", "updated_at"])
        return {"ok": False, "message": message, "data": {}}

    @staticmethod
    def _notify(request, result: dict):
        try:
            from notifications.shortcuts import notify

            ok = result.get("ok")
            notify(
                request.user,
                "ORDER_CREATED" if ok and "TRADE" in request.action_type else
                ("SECURITY_ALERT" if "KILL_SWITCH" in request.action_type else
                 "ORDER_FAILED" if not ok else "ORDER_SUBMITTED"),
                title=f"Assistant : {request.get_action_type_display()} — "
                      f"{'OK' if ok else 'ÉCHEC'}",
                message=result.get("message", request.summary)[:500],
                payload={"action_request_id": request.id, "mode": request.mode},
                dedupe_key=f"assistant_action:{request.id}",
            )
        except Exception:
            log.exception("assistant.action_notify_failed request=%s", request.id)

    @staticmethod
    def _audit(request, *, final_decision: str, notes: str, order=None,
               risk_decision=None):
        try:
            from trading.models_ai import DecisionAudit

            DecisionAudit.objects.create(
                user=request.user,
                portfolio_id=request.payload.get("portfolio_id"),
                order=order,
                risk_decision=risk_decision,
                ai_output={"assistant_action_request_id": request.id,
                           "intent": request.intent,
                           "summary": request.summary},
                risk_output=request.risk_summary or {},
                execution_output=request.result or {},
                final_decision=final_decision,
                notes=notes[:500],
            )
        except Exception:
            log.exception("assistant.audit_failed request=%s", request.id)

    # ------------------------------------------------------------------
    # Exécuteurs
    # ------------------------------------------------------------------
    @classmethod
    def _exec_execute_trade_idea(cls, request) -> dict:
        from brokers.models import BrokerAccount
        from portfolio.models import Portfolio
        from trading.models import TradeIdea
        from trading.services.trade_idea_execution import TradeIdeaExecutionService

        idea = TradeIdea.objects.filter(
            pk=request.target_id, user=request.user,
        ).first()
        if idea is None:
            return {"ok": False, "message": "Trade idea introuvable.", "data": {}}

        portfolio = Portfolio.objects.filter(
            pk=request.payload.get("portfolio_id"), user=request.user,
        ).first()
        broker_account = BrokerAccount.objects.filter(
            pk=request.payload.get("broker_account_id"), user=request.user,
        ).first()
        if portfolio is None or broker_account is None:
            return {"ok": False, "message": "Portefeuille ou broker introuvable.", "data": {}}

        outcome = TradeIdeaExecutionService.execute(
            idea,
            broker_account,
            portfolio,
            Decimal(str(request.payload.get("stake_amount"))),
        )
        order = outcome.get("order")
        approval = outcome.get("approval")

        if order is None:
            reason = getattr(approval, "blocking_reason", "") or "Exécution refusée par le Risk Engine."
            cls._audit(request, final_decision="BLOCKED", notes=reason,
                       risk_decision=outcome.get("risk_decision"))
            return {"ok": False, "message": f"Bloqué : {reason}", "data": {
                "risk_decision_id": getattr(outcome.get("risk_decision"), "id", None),
            }}

        cls._audit(request, final_decision="EXECUTED",
                   notes="Exécution via assistant après confirmation.",
                   order=order, risk_decision=outcome.get("risk_decision"))
        return {
            "ok": True,
            "message": f"Ordre créé et soumis avec succès. Statut : {order.status}.",
            "data": {"order_id": order.id, "order_status": order.status,
                     "symbol": order.symbol, "side": order.side},
        }

    # PREPARE_TRADE confirmé = même exécution
    _exec_prepare_trade = _exec_execute_trade_idea

    @classmethod
    def _exec_approve_trade_idea(cls, request) -> dict:
        from trading.models import TradeIdea

        idea = TradeIdea.objects.filter(pk=request.target_id, user=request.user).first()
        if idea is None:
            return {"ok": False, "message": "Trade idea introuvable.", "data": {}}
        idea.status = "APPROVED"
        idea.save(update_fields=["status", "updated_at"])
        cls._audit(request, final_decision="APPROVED", notes="Approbation via assistant.")
        return {"ok": True, "message": f"Idée {idea.direction} {idea.symbol} approuvée.",
                "data": {"idea_id": idea.id}}

    @classmethod
    def _exec_reject_trade_idea(cls, request) -> dict:
        from trading.models import TradeIdea

        idea = TradeIdea.objects.filter(pk=request.target_id, user=request.user).first()
        if idea is None:
            return {"ok": False, "message": "Trade idea introuvable.", "data": {}}
        idea.status = "REJECTED"
        idea.save(update_fields=["status", "updated_at"])
        cls._audit(request, final_decision="BLOCKED", notes="Rejet via assistant.")
        return {"ok": True, "message": f"Idée {idea.direction} {idea.symbol} rejetée.",
                "data": {"idea_id": idea.id}}

    @classmethod
    def _exec_cancel_order(cls, request) -> dict:
        from execution.models import Order
        from execution.services import ExecutionOrchestrator

        order = Order.objects.filter(pk=request.target_id, user=request.user).first()
        if order is None:
            return {"ok": False, "message": "Ordre introuvable.", "data": {}}
        cancelled = ExecutionOrchestrator.cancel_order(order)
        cls._audit(request, final_decision="EXECUTED",
                   notes="Annulation d'ordre via assistant.", order=cancelled)
        return {"ok": True,
                "message": f"Ordre #{cancelled.id} ({cancelled.symbol}) annulé. "
                           f"Le cash réservé a été libéré.",
                "data": {"order_id": cancelled.id, "status": cancelled.status}}

    @classmethod
    def _close_or_reduce(cls, request, fraction: Decimal) -> dict:
        """Ferme (fraction=1) ou réduit une position en soumettant un ordre
        OPPOSÉ via l'orchestrateur — jamais d'appel broker direct."""
        from execution.services import ExecutionOrchestrator
        from portfolio.models import Position

        position = Position.objects.filter(
            pk=request.target_id, portfolio__user=request.user,
            status__in=["OPEN", "PARTIALLY_CLOSED"],
        ).select_related("portfolio", "broker_account", "asset").first()
        if position is None:
            return {"ok": False, "message": "Position introuvable ou déjà fermée.", "data": {}}

        qty = (Decimal(str(position.quantity)) * fraction).quantize(Decimal("0.00000001"))
        if qty <= 0:
            return {"ok": False, "message": "Quantité à clôturer nulle.", "data": {}}

        price = Decimal(str(position.current_price or position.average_entry_price or 0))
        side = "SELL" if position.side == "LONG" else "BUY"
        order = ExecutionOrchestrator.create_order(
            user=request.user,
            portfolio=position.portfolio,
            broker_account=position.broker_account,
            symbol=position.symbol,
            side=side,
            approved_quantity=qty,
            requested_stake_amount=(qty * price).quantize(Decimal("0.01")),
            approved_notional=(qty * price).quantize(Decimal("0.01")),
            requested_price=price,
            asset=position.asset,
            source="AI_ASSISTED",
            metadata={"assistant_action_request_id": request.id,
                      "closes_position_id": position.id,
                      "close_fraction": str(fraction)},
        )
        submitted = ExecutionOrchestrator.submit_order(order)
        cls._audit(request, final_decision="EXECUTED",
                   notes=f"Clôture {fraction:.0%} via assistant.", order=submitted)
        return {
            "ok": True,
            "message": (
                f"Ordre de {'clôture totale' if fraction == 1 else f'réduction {fraction:.0%}'} "
                f"soumis sur {position.symbol} ({side} {qty}). Statut : {submitted.status}."
            ),
            "data": {"order_id": submitted.id, "position_id": position.id,
                     "status": submitted.status},
        }

    @classmethod
    def _exec_close_position(cls, request) -> dict:
        return cls._close_or_reduce(request, Decimal("1"))

    @classmethod
    def _exec_reduce_position(cls, request) -> dict:
        pct = Decimal(str(request.payload.get("percent", 50))) / Decimal("100")
        pct = max(Decimal("0.01"), min(pct, Decimal("1")))
        return cls._close_or_reduce(request, pct)

    @classmethod
    def _exec_sync_portfolio(cls, request) -> dict:
        from execution.reconciliation import BrokerReconciliationService
        from portfolio.models import Portfolio
        from portfolio.services import PortfolioService

        portfolio = Portfolio.objects.filter(
            pk=request.payload.get("portfolio_id"), user=request.user,
        ).first()
        if portfolio is None:
            return {"ok": False, "message": "Portefeuille introuvable.", "data": {}}
        recon = BrokerReconciliationService.reconcile_orders(portfolio)
        PortfolioService.refresh_portfolio_metrics(portfolio)
        return {
            "ok": True,
            "message": (
                f"Portefeuille « {portfolio.name} » synchronisé : "
                f"{recon.processed_count} ordre(s) réconcilié(s), "
                f"{recon.error_count} erreur(s)."
            ),
            "data": {"processed": recon.processed_count, "errors": recon.error_count},
        }

    @classmethod
    def _exec_test_broker(cls, request) -> dict:
        from brokers.models import BrokerAccount
        from brokers.services_connection import BrokerConnectionService

        broker = BrokerAccount.objects.filter(
            pk=request.target_id, user=request.user,
        ).first()
        if broker is None:
            return {"ok": False, "message": "Compte broker introuvable.", "data": {}}
        outcome = BrokerConnectionService.test_connection(broker)
        ok = bool(outcome.get("success"))
        return {
            "ok": ok,
            "message": (f"Connexion à « {broker.name} » OK." if ok
                        else f"Connexion à « {broker.name} » en échec : "
                             f"{outcome.get('error', 'erreur inconnue')[:200]}"),
            "data": {"broker_account_id": broker.id, "success": ok},
        }

    @classmethod
    def _exec_activate_kill_switch(cls, request) -> dict:
        from portfolio.models import Portfolio
        from risk.services import RiskGuardService

        portfolio = Portfolio.objects.filter(
            pk=request.payload.get("portfolio_id"), user=request.user,
        ).first()
        if portfolio is None:
            return {"ok": False, "message": "Portefeuille introuvable.", "data": {}}
        profile = RiskGuardService.get_default_profile(portfolio)
        RiskGuardService.trigger_kill_switch(
            portfolio, profile, "MANUAL",
            "Kill switch activé manuellement via l'assistant.",
        )
        cls._audit(request, final_decision="EXECUTED", notes="Kill switch manuel (assistant).")
        return {"ok": True,
                "message": f"🛑 Kill switch ACTIVÉ sur « {portfolio.name} » : "
                           f"plus aucune nouvelle entrée ne sera exécutée.",
                "data": {"portfolio_id": portfolio.id}}

    @classmethod
    def _exec_deactivate_kill_switch(cls, request) -> dict:
        from portfolio.models import Portfolio
        from risk.services import RiskGuardService

        portfolio = Portfolio.objects.filter(
            pk=request.payload.get("portfolio_id"), user=request.user,
        ).first()
        if portfolio is None:
            return {"ok": False, "message": "Portefeuille introuvable.", "data": {}}
        RiskGuardService.resolve_kill_switch(portfolio)
        return {"ok": True,
                "message": f"Kill switch levé sur « {portfolio.name} » — le trading peut reprendre.",
                "data": {"portfolio_id": portfolio.id}}

    @classmethod
    def _exec_disable_auto_trading(cls, request) -> dict:
        from trading.models import TradeIdea

        ideas = TradeIdea.objects.filter(
            user=request.user, auto_trade_enabled=True,
        ).update(auto_trade_enabled=False)
        cls._audit(request, final_decision="EXECUTED", notes="Auto-trading désactivé (assistant).")
        return {"ok": True,
                "message": f"Auto-trading désactivé : {ideas} idée(s) repassée(s) en "
                           f"validation manuelle. Aucune exécution automatique ne partira.",
                "data": {"ideas_disabled": ideas}}

    @classmethod
    def _exec_enable_auto_trading(cls, request) -> dict:
        # Réactivation volontairement ciblée : uniquement les idées APPROVED.
        from trading.models import TradeIdea

        ideas = TradeIdea.objects.filter(
            user=request.user, status="APPROVED",
        ).update(auto_trade_enabled=True)
        return {"ok": True,
                "message": f"Auto-trading réactivé sur {ideas} idée(s) approuvée(s).",
                "data": {"ideas_enabled": ideas}}
