from __future__ import annotations

from decimal import Decimal
import logging

from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone

from brokers.services.deriv import DerivClient
from portfolio.models import Portfolio, Position
from trading.models import DerivContract, TradeIdea, TradeIdeaFeedback
from trading.services.agents.orchestrator import TradingIntelligenceOrchestrator
from trading.services.agents.portfolio_advisor_agent import PortfolioAdvisorAgent
from trading.services.hedge_fund.engine import AIHedgeFundEngine
from trading.services.hedge_fund.learning_agent import LearningAgent
from trading.services.trade_idea_generation import TradeIdeaGenerationService

logger = logging.getLogger(__name__)
User = get_user_model()


def _active_users_queryset():
    return User.objects.filter(is_active=True).order_by("id")


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def sync_open_deriv_contracts_task(self):
    """
    Surveille les DerivContract(status=OPEN) et délègue le règlement complet à
    on_open_contract_update → DerivSettlementService.

    Ce chemin couvre les contrats créés via DerivExecutor (QuickTrade, auto-trade direct).
    Les contrats créés via ExecutionOrchestrator (IA path) sont couverts par
    sync_execution_deriv_contracts_task.
    """
    from brokers.services.deriv_sync import on_open_contract_update

    contracts = (
        DerivContract.objects
        .filter(status="OPEN", is_expired=False)
        .select_related("broker_account", "order", "signal")
    )

    summary = {
        "total": contracts.count(),
        "updated": 0,
        "settled": 0,
        "failed": 0,
    }

    for contract in contracts:
        client = None
        try:
            broker_account = contract.broker_account
            client = DerivClient(
                token=broker_account.deriv_token,
                app_id=broker_account.deriv_app_id,
            )

            accounts_resp = client.list_options_accounts()
            accounts = accounts_resp.get("data", [])
            if not accounts:
                raise RuntimeError("Aucun compte options Deriv disponible.")

            preferred_type = (broker_account.deriv_account_type or "demo").lower()
            selected = None
            for acc in accounts:
                if str(acc.get("account_type", "")).lower() == preferred_type:
                    selected = acc
                    break
            if not selected:
                selected = accounts[0]

            account_id = selected.get("account_id")
            if not account_id:
                raise RuntimeError(f"Compte Deriv invalide: {selected}")

            ws_url = client.get_otp_ws_url(account_id)
            client.connect_with_otp_url(ws_url)

            resp = client.proposal_open_contract(contract_id=contract.contract_id)
            poc = resp.get("proposal_open_contract", {})

            if not poc:
                logger.warning(
                    "sync_open_deriv: poc vide pour contract_id=%s — ignoré",
                    contract.contract_id,
                )
                summary["updated"] += 1
                continue

            # Déléguer entièrement le règlement à DerivSettlementService via le dispatcher
            # (ferme Position, crée Trade, crédite Portfolio, rafraîchit métriques)
            on_open_contract_update(
                broker_account_id=broker_account.id,
                payload=poc,
            )

            # Compter comme settled si le poc indique un état terminal
            poc_status = (poc.get("status") or "").lower()
            is_terminal = (
                bool(poc.get("is_sold"))
                or bool(poc.get("is_settleable"))
                or poc_status in ("won", "lost", "expired")
            )
            if is_terminal:
                summary["settled"] += 1

            summary["updated"] += 1

        except Exception as exc:
            try:
                contract.error_message = str(exc)
                contract.save(update_fields=["error_message", "updated_at"])
            except Exception:
                pass
            summary["failed"] += 1
            logger.exception("Deriv contract sync failed for contract_id=%s", contract.contract_id)

        finally:
            if client:
                try:
                    client.close()
                except Exception:
                    pass

    return summary


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def sync_execution_deriv_contracts_task(self):
    """
    Surveille les execution.models.Order créés par ExecutionOrchestrator (chemin IA)
    dont le broker est DERIV et qui sont encore en statut SUBMITTED/PARTIALLY_FILLED.

    Ces ordres n'ont PAS de DerivContract associé (le chemin IA ne passe pas par
    DerivExecutor), donc sync_open_deriv_contracts_task ne les voit jamais.
    Cette tâche comble ce manque : elle interroge Deriv via broker_order_id et
    délègue à on_open_contract_update → PATH 2 (BrokerExternalRef) ou PATH 3 (import).

    Fréquence recommandée : toutes les 30 secondes (les contrats Deriv expirent vite).
    """
    from brokers.services.deriv_sync import on_open_contract_update
    from execution.models import Order as ExecutionOrder

    orders = (
        ExecutionOrder.objects
        .filter(
            broker_account__broker="DERIV",
            status__in=["SUBMITTED", "PARTIALLY_FILLED"],
            broker_order_id__isnull=False,
        )
        .exclude(broker_order_id="")
        .select_related("broker_account")
    )

    summary = {
        "total": orders.count(),
        "updated": 0,
        "settled": 0,
        "failed": 0,
    }

    for order in orders:
        client = None
        try:
            broker_account = order.broker_account
            client = DerivClient(
                token=broker_account.deriv_token,
                app_id=broker_account.deriv_app_id,
            )

            accounts_resp = client.list_options_accounts()
            accounts = accounts_resp.get("data", [])
            if not accounts:
                raise RuntimeError("Aucun compte options Deriv disponible.")

            preferred_type = (broker_account.deriv_account_type or "demo").lower()
            selected = None
            for acc in accounts:
                if str(acc.get("account_type", "")).lower() == preferred_type:
                    selected = acc
                    break
            if not selected:
                selected = accounts[0]

            account_id = selected.get("account_id")
            if not account_id:
                raise RuntimeError(f"Compte Deriv invalide: {selected}")

            ws_url = client.get_otp_ws_url(account_id)
            client.connect_with_otp_url(ws_url)

            resp = client.proposal_open_contract(contract_id=order.broker_order_id)
            poc = resp.get("proposal_open_contract", {})

            if not poc:
                logger.warning(
                    "sync_execution_deriv: poc vide broker_order_id=%s order_id=%s — ignoré",
                    order.broker_order_id, order.id,
                )
                summary["updated"] += 1
                continue

            # Déléguer entièrement le règlement au dispatcher
            on_open_contract_update(
                broker_account_id=broker_account.id,
                payload=poc,
            )

            poc_status = (poc.get("status") or "").lower()
            is_terminal = (
                bool(poc.get("is_sold"))
                or bool(poc.get("is_settleable"))
                or poc_status in ("won", "lost", "expired")
            )
            if is_terminal:
                summary["settled"] += 1

            summary["updated"] += 1

        except Exception as exc:
            logger.exception(
                "sync_execution_deriv: échec order_id=%s broker_order_id=%s err=%s",
                order.id, getattr(order, "broker_order_id", None), exc,
            )
            summary["failed"] += 1

        finally:
            if client:
                try:
                    client.close()
                except Exception:
                    pass

    return summary


@shared_task
def scan_market_1m_task():
    total_generated = 0
    results = []

    for user in _active_users_queryset():
        try:
            ideas = TradeIdeaGenerationService.generate(
                timeframe_code="5m",
                user=user,
            )
            count = len(ideas)
            total_generated += count
            results.append({
                "user_id": user.id,
                "generated": count,
                "status": "ok",
            })
        except Exception as exc:
            logger.exception("scan_market_1m_task failed for user_id=%s", user.id)
            results.append({
                "user_id": user.id,
                "generated": 0,
                "status": "error",
                "error": str(exc),
            })

    return {
        "generated": total_generated,
        "schedule": "1m",
        "results": results,
    }


@shared_task
def scan_market_5m_task():
    total_generated = 0
    results = []

    for user in _active_users_queryset():
        try:
            ideas = TradeIdeaGenerationService.generate(
                timeframe_code="15m",
                user=user,
            )
            count = len(ideas)
            total_generated += count
            results.append({
                "user_id": user.id,
                "generated": count,
                "status": "ok",
            })
        except Exception as exc:
            logger.exception("scan_market_5m_task failed for user_id=%s", user.id)
            results.append({
                "user_id": user.id,
                "generated": 0,
                "status": "error",
                "error": str(exc),
            })

    return {
        "generated": total_generated,
        "schedule": "5m",
        "results": results,
    }


@shared_task
def expire_trade_ideas_task():
    now = timezone.now()
    count = TradeIdea.objects.filter(
        status__in=["NEW", "REVIEW", "APPROVED"],
        expires_at__lte=now,
    ).update(status="EXPIRED")
    return {"expired": count}


@shared_task
def learn_from_trade_ideas_task():
    updated = 0

    feedbacks = TradeIdeaFeedback.objects.select_related("idea").filter(outcome="OPEN")
    for feedback in feedbacks:
        idea = feedback.idea

        if not idea or idea.status != "EXECUTED":
            continue

        position = Position.objects.filter(
            portfolio__orders__id=feedback.order_id
        ).order_by("-created_at").first()

        if not position:
            continue

        pnl = position.pnl or 0
        feedback.pnl_amount = pnl
        feedback.pnl_percent = float(position.pnl_percent or 0)

        if position.status == "OPEN":
            feedback.outcome = "OPEN"
        else:
            if pnl > 0:
                feedback.outcome = "WIN"
                feedback.hit_take_profit = True
            elif pnl < 0:
                feedback.outcome = "LOSS"
                feedback.hit_stop_loss = True
            else:
                feedback.outcome = "BREAKEVEN"

        feedback.execution_status = position.status
        feedback.evaluated_at = timezone.now()
        feedback.learning_payload = {
            "idea_score": idea.overall_score,
            "confidence": idea.confidence_score,
            "risk": idea.risk_score,
            "reward": idea.reward_score,
            "direction": idea.direction,
            "symbol": idea.symbol,
        }
        feedback.save()
        updated += 1

    return {"updated_feedbacks": updated}


@shared_task
def run_ai_market_cycle_1m():
    total_ideas = 0
    total_reviews = 0
    results = []

    for user in _active_users_queryset():
        try:
            result = TradingIntelligenceOrchestrator.run_market_cycle(
                timeframe_code="5m",
                user=user,
            )
            ideas_count = len(result.get("ideas", []))
            reviews_count = len(result.get("reviews", []))
            regime_snapshot = result.get("regime_snapshot")

            total_ideas += ideas_count
            total_reviews += reviews_count

            results.append({
                "user_id": user.id,
                "ideas": ideas_count,
                "reviews": reviews_count,
                "regime": regime_snapshot.regime if regime_snapshot else None,
                "status": "ok",
            })
        except Exception as exc:
            logger.exception("run_ai_market_cycle_1m failed for user_id=%s", user.id)
            results.append({
                "user_id": user.id,
                "ideas": 0,
                "reviews": 0,
                "regime": None,
                "status": "error",
                "error": str(exc),
            })

    return {
        "ideas": total_ideas,
        "reviews": total_reviews,
        "results": results,
    }


@shared_task
def run_ai_market_cycle_5m():
    total_ideas = 0
    total_reviews = 0
    results = []

    for user in _active_users_queryset():
        try:
            result = TradingIntelligenceOrchestrator.run_market_cycle(
                timeframe_code="15m",
                user=user,
            )
            ideas_count = len(result.get("ideas", []))
            reviews_count = len(result.get("reviews", []))
            regime_snapshot = result.get("regime_snapshot")

            total_ideas += ideas_count
            total_reviews += reviews_count

            results.append({
                "user_id": user.id,
                "ideas": ideas_count,
                "reviews": reviews_count,
                "regime": regime_snapshot.regime if regime_snapshot else None,
                "status": "ok",
            })
        except Exception as exc:
            logger.exception("run_ai_market_cycle_5m failed for user_id=%s", user.id)
            results.append({
                "user_id": user.id,
                "ideas": 0,
                "reviews": 0,
                "regime": None,
                "status": "error",
                "error": str(exc),
            })

    return {
        "ideas": total_ideas,
        "reviews": total_reviews,
        "results": results,
    }


@shared_task
def refresh_portfolio_advice():
    count = 0
    for portfolio in Portfolio.objects.all():
        PortfolioAdvisorAgent.advise(portfolio)
        count += 1
    return {"portfolios_reviewed": count}


@shared_task
def expire_old_trade_ideas():
    now = timezone.now()

    qs = TradeIdea.objects.filter(
        status__in=["NEW", "REVIEW", "APPROVED"],
        expires_at__isnull=False,
        expires_at__lte=now,
    )

    expired = qs.update(status="EXPIRED")
    return {"expired": expired}


@shared_task
def run_hedge_fund_generation_cycle():
    total_ideas = 0
    results = []

    users = User.objects.filter(is_active=True).order_by("id")

    for user in users:
        try:
            result = AIHedgeFundEngine.run_generation_cycle(
                timeframe_code="1h",
                user=user,
            )

            ideas_count = len(result.get("ideas", []))
            regime = result.get("regime")

            total_ideas += ideas_count
            results.append({
                "user_id": user.id,
                "ideas": ideas_count,
                "regime": regime.regime if regime else None,
                "status": "ok",
            })

        except Exception as exc:
            logger.exception("run_hedge_fund_generation_cycle failed for user_id=%s", user.id)
            results.append({
                "user_id": user.id,
                "ideas": 0,
                "regime": None,
                "status": "error",
                "error": str(exc),
            })

    return {
        "ideas": total_ideas,
        "results": results,
    }


@shared_task
def run_hedge_fund_execution_cycle():
    executed = 0
    for portfolio in Portfolio.objects.select_related("broker_account").all():
        broker = portfolio.broker_account
        if not broker or not broker.is_active:
            continue

        order = AIHedgeFundEngine.execute_top_idea_for_portfolio(
            portfolio=portfolio,
            broker_account=broker,
        )
        if order:
            executed += 1

    return {"executed_orders": executed}


@shared_task
def run_learning_refresh_cycle():
    updated = 0
    feedbacks = TradeIdeaFeedback.objects.filter(
        outcome__in=["WIN", "LOSS", "BREAKEVEN"]
    ).select_related("idea__strategy")

    strategy_ids = set()
    for feedback in feedbacks:
        if feedback.idea and feedback.idea.strategy_id:
            strategy_ids.add(feedback.idea.strategy_id)
            LearningAgent.reinforcement_from_feedback(feedback)

    from strategies.models import Strategy
    for strategy in Strategy.objects.filter(id__in=strategy_ids):
        LearningAgent.refresh_for_strategy(strategy)
        updated += 1

    return {"updated_learning_snapshots": updated}

# Enregistre les tâches IA du module annexe dans le worker (cf. brokers/tasks.py).
from trading import tasks_ai  # noqa: E402,F401
