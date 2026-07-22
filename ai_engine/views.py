"""
ai_engine/views.py
==================

API REST pour interroger l'IA :
  POST /ai/advise/trade-idea/<idea_id>/   → AIDecision JSON
  GET  /ai/decisions/                      → liste paginée des décisions de l'utilisateur

Sécurité :
  - login_required obligatoire
  - **Vérification d'ownership** : un utilisateur ne peut interroger l'IA que
    sur les TradeIdea qu'il possède (via le portfolio attaché ou le user direct)
  - **Rate limiting** : cap des appels Claude pour éviter le DoS coût
  - Pas de fuite de données techniques (cost_usd, raw prompts) côté front
"""

from __future__ import annotations

import logging

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST, require_GET

from .integrations import advise_for_trade_idea
from .models import AIDecisionLog


log = logging.getLogger("lyneci.ai_engine.views")


# Cap par utilisateur — modifiable via settings.AI_RATE_LIMIT_PER_HOUR
AI_RATE_LIMIT_PER_HOUR_DEFAULT = 30
AI_RATE_LIMIT_WINDOW_SECONDS = 3600


def _ai_rate_limit_check(user_id: int) -> tuple[bool, int, int]:
    """
    Retourne (allowed, used, limit). Compte les appels par utilisateur sur
    une fenêtre glissante de 1h via Redis (django cache).

    Si Redis indisponible → on autorise (fail-open) mais on log un WARNING.
    """
    from django.conf import settings
    limit = int(getattr(settings, "AI_RATE_LIMIT_PER_HOUR", AI_RATE_LIMIT_PER_HOUR_DEFAULT))
    cache_key = f"ai_rate:{user_id}"

    try:
        used = cache.get(cache_key) or 0
        used = int(used)
        if used >= limit:
            return False, used, limit
        # Increment with TTL
        new_used = cache.incr(cache_key) if used > 0 else 1
        if new_used == 1:
            cache.expire(cache_key, AI_RATE_LIMIT_WINDOW_SECONDS)
        return True, new_used, limit
    except Exception as exc:
        log.warning("ai_rate_limit.cache_unavailable user_id=%s err=%s — fail-open", user_id, exc)
        # Fallback : si Redis ne fonctionne pas, on incrémente quand même via simple set
        try:
            cache.set(cache_key, (cache.get(cache_key) or 0) + 1, AI_RATE_LIMIT_WINDOW_SECONDS)
        except Exception:
            pass
        return True, 0, limit


def _user_owns_trade_idea(user, idea) -> bool:
    """
    Vérifie que l'utilisateur a légitimement accès à cette trade idea.
    Sources d'autorité, dans l'ordre :
      - idea.user (si le modèle a ce champ direct)
      - idea.portfolio.user
      - idea.broker_account.user
    """
    if getattr(idea, "user_id", None) and idea.user_id == user.id:
        return True
    pf = getattr(idea, "portfolio", None)
    if pf and getattr(pf, "user_id", None) == user.id:
        return True
    ba = getattr(idea, "broker_account", None)
    if ba and getattr(ba, "user_id", None) == user.id:
        return True
    return False


@login_required
@require_POST
def advise_trade_idea_view(request, idea_id: int):
    """
    Demande un nouvel avis IA pour une trade idea.
    """
    from trading.models import TradeIdea

    idea = get_object_or_404(TradeIdea, pk=idea_id)

    # 1. Ownership check (CRITIQUE — évite la fuite de stratégies entre users)
    if not _user_owns_trade_idea(request.user, idea):
        log.warning(
            "ai.advise.forbidden user_id=%s idea_id=%s — trying to access other user's idea",
            request.user.id, idea_id,
        )
        return HttpResponseForbidden(
            JsonResponse({"detail": "Accès interdit à cette trade idea."}, status=403).content,
        )

    # 2. Rate limiting (évite le DoS coût Claude)
    allowed, used, limit = _ai_rate_limit_check(request.user.id)
    if not allowed:
        log.info("ai.advise.rate_limited user_id=%s used=%s limit=%s", request.user.id, used, limit)
        resp = JsonResponse({
            "detail": f"Limite d'appels IA atteinte ({limit}/heure). Réessaie plus tard.",
            "rate_limit": {"used": used, "limit": limit, "window_seconds": AI_RATE_LIMIT_WINDOW_SECONDS},
        }, status=429)
        resp["Retry-After"] = str(AI_RATE_LIMIT_WINDOW_SECONDS)
        return resp

    portfolio = getattr(idea, "portfolio", None)
    if portfolio is None:
        from portfolio.models import Portfolio
        portfolio = Portfolio.objects.filter(
            user=request.user, is_active=True,
        ).order_by("-is_default").first()

    decision = advise_for_trade_idea(idea, user=request.user, portfolio=portfolio)

    # NB : on N'EXPOSE PAS au front cost_usd / model_name complet / latency_ms.
    # Ces données sensibles restent dans AIDecisionLog (visible aux admins).
    return JsonResponse({
        "decision": decision.decision,
        "confidence": decision.confidence,
        "direction": decision.direction,
        "expected_rr": decision.expected_rr,
        "suggested_stake": str(decision.suggested_stake) if decision.suggested_stake else None,
        "suggested_stop_loss": str(decision.suggested_stop_loss) if decision.suggested_stop_loss else None,
        "suggested_take_profit": str(decision.suggested_take_profit) if decision.suggested_take_profit else None,
        "rationale": decision.rationale,
        "risks": decision.risks,
        "provider": decision.provider,
        # Indicateur générique pour le front, pas le coût réel
        "is_fallback": decision.provider == "HEURISTIC",
        "rate_limit": {"used": used, "limit": limit},
    })


@login_required
@require_GET
def list_decisions_view(request):
    qs = AIDecisionLog.objects.filter(user=request.user).order_by("-created_at")[:50]
    rows = [
        {
            "id": d.id,
            "created_at": d.created_at.isoformat(),
            "symbol": d.symbol,
            "decision": d.decision,
            "confidence": d.confidence,
            "provider": d.provider,
            "fallback_used": d.fallback_used,
            "rationale": d.rationale,
        }
        for d in qs
    ]
    return JsonResponse({"results": rows, "count": len(rows)})


@login_required
def ai_performance_view(request):
    """Centre IA — score de performance, calibration, historique (données réelles)."""
    from .services_performance import AIPerformanceService, PredictionEvaluationService

    try:
        days = max(1, min(int(request.GET.get("days", 30)), 365))
    except (TypeError, ValueError):
        days = 30

    scope_user = None if request.GET.get("scope") == "platform" else request.user

    return JsonResponse({
        "summary": AIPerformanceService.summary(user=scope_user, days=days),
        "history": AIPerformanceService.recommendation_history(user=scope_user, limit=30),
        "prediction_accuracy": PredictionEvaluationService.accuracy(days=days),
    })
