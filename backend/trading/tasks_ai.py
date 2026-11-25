from celery import shared_task
from django.utils import timezone

from portfolio.models import Portfolio
from .models_ai import MarketOpportunity, TradeRecommendation
from .services.ai_engine import AIRecommendationService
from .services.opportunity_engine import OpportunityEngine


@shared_task
def expire_market_opportunities_task():
    return {"expired_count": OpportunityEngine.expire_old_opportunities()}


@shared_task
def expire_trade_recommendations_task():
    now = timezone.now()
    qs = TradeRecommendation.objects.filter(
        status__in=["PENDING", "APPROVED_BY_AI", "APPROVED_BY_USER"],
        expires_at__lt=now,
    )
    count = qs.update(status="EXPIRED", updated_at=timezone.now())
    return {"expired_count": count}


@shared_task
def generate_ai_recommendations_for_portfolio_task(portfolio_id: int):
    portfolio = Portfolio.objects.filter(id=portfolio_id, is_active=True, broker_account__is_active=True).first()
    if not portfolio:
        return {"status": "missing"}

    opportunities = MarketOpportunity.objects.filter(
        status="ACTIVE"
    ).order_by("-overall_score")[:20]

    created = []
    for opportunity in opportunities:
        exists = TradeRecommendation.objects.filter(
            user=portfolio.user,
            portfolio=portfolio,
            opportunity=opportunity,
            status__in=["PENDING", "APPROVED_BY_AI", "APPROVED_BY_USER", "EXECUTED"],
        ).exists()
        if exists:
            continue

        recommendation = AIRecommendationService.create_recommendation(
            user=portfolio.user,
            portfolio=portfolio,
            broker_account=portfolio.broker_account,
            opportunity=opportunity,
        )
        created.append(recommendation.id)

    return {
        "status": "ok",
        "created_count": len(created),
        "recommendation_ids": created,
    }


@shared_task
def generate_ai_recommendations_for_all_portfolios_task():
    payload = []
    for portfolio in Portfolio.objects.filter(is_active=True, broker_account__is_active=True):
        result = generate_ai_recommendations_for_portfolio_task(portfolio.id)
        payload.append({
            "portfolio_id": portfolio.id,
            "result": result,
        })
    return payload