"""
ai_engine/services.py
=====================

AITradeAdvisor : orchestrateur de providers IA.

Stratégie :
  1. Choisir le provider préféré (settings.AI_PRIMARY_PROVIDER, défaut = "CLAUDE")
  2. Si indisponible → tenter le secondaire (settings.AI_SECONDARY_PROVIDER, défaut = "OLLAMA")
  3. Si tout échoue → fallback HeuristicProvider (toujours disponible)
  4. Logger TOUTE décision dans AIDecisionLog (audit, retraining)

Configuration (settings) :
    AI_PRIMARY_PROVIDER   = "CLAUDE" | "DEEPSEEK" | "OLLAMA" | "HEURISTIC"
    AI_SECONDARY_PROVIDER = "DEEPSEEK" | "CLAUDE" | "OLLAMA" | "HEURISTIC" | None
    ANTHROPIC_API_KEY     = "..."
    AI_CLAUDE_MODEL       = "claude-opus-4-5"
    DEEPSEEK_API_KEY      = "sk-..."
    AI_DEEPSEEK_MODEL     = "deepseek-chat"      # ou "deepseek-reasoner" (R1)
    AI_DEEPSEEK_BASE_URL  = "https://api.deepseek.com"   # optionnel
    AI_DEEPSEEK_TIMEOUT   = 60.0
    AI_OLLAMA_BASE_URL    = "http://localhost:11434"
    AI_OLLAMA_MODEL       = "llama3"
    AI_FORCE_FALLBACK     = False  # mettre True pour désactiver les LLMs (test/économie)
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .models import AIDecisionLog
from .providers.base import AIDecision, MarketContext, ProviderUnavailable
from .providers.heuristic import HeuristicProvider


log = logging.getLogger("leotrade.ai_engine.advisor")


def _get_provider_instance(name: str):
    name = (name or "").upper()
    if name == "CLAUDE":
        from .providers.claude import ClaudeProvider
        return ClaudeProvider()
    if name == "DEEPSEEK":
        from .providers.deepseek import DeepSeekProvider
        return DeepSeekProvider()
    if name == "OLLAMA":
        from .providers.ollama import OllamaProvider
        return OllamaProvider()
    if name == "HEURISTIC":
        return HeuristicProvider()
    return None


class AITradeAdvisor:
    """
    Point d'entrée unique pour obtenir un avis IA sur un setup de marché.

    Usage typique (dans une task Celery, ou une vue) :
        ctx = MarketContext(...)
        decision = AITradeAdvisor.advise(
            user=user, portfolio=portfolio, trade_idea=idea, context=ctx,
        )
        if decision.decision == "EXECUTE":
            ExecutionOrchestrator.submit(OrderIntent(...))
    """

    # Limite : N appels IA maximum par utilisateur sur une fenêtre glissante d'1h.
    # Configurable via settings.AI_RATE_LIMIT_PER_HOUR (défaut 60).
    # Evite la consommation abusive de tokens Claude (facturation) et les
    # attaques par saturation du pipeline de trading.
    _RATE_LIMIT_WINDOW = 3600  # 1 heure en secondes
    _RATE_LIMIT_DEFAULT = 60   # appels max / heure / user

    @classmethod
    def _check_rate_limit(cls, user) -> bool:
        """
        Retourne True si l'utilisateur peut encore faire un appel IA.
        Incrément atomique sur une clé Redis avec TTL.
        """
        if user is None:
            return True  # appels système (tasks Celery sans user) non limités

        limit = getattr(settings, "AI_RATE_LIMIT_PER_HOUR", cls._RATE_LIMIT_DEFAULT)
        cache_key = f"ai_rate:{user.pk}"

        count = cache.get(cache_key, 0)
        if count >= limit:
            return False

        # Incrémente et (re)initialise le TTL si c'est le premier appel de la fenêtre
        new_count = count + 1
        cache.set(cache_key, new_count, cls._RATE_LIMIT_WINDOW)
        return True

    @staticmethod
    def get_provider_chain() -> list:
        """
        Retourne la liste des providers à essayer dans l'ordre.
        Le HeuristicProvider est TOUJOURS en fin de chaîne (filet de sécurité).
        """
        if getattr(settings, "AI_FORCE_FALLBACK", False):
            return [HeuristicProvider()]

        chain = []
        primary = getattr(settings, "AI_PRIMARY_PROVIDER", "CLAUDE")
        secondary = getattr(settings, "AI_SECONDARY_PROVIDER", "OLLAMA")

        for name in (primary, secondary):
            if not name:
                continue
            inst = _get_provider_instance(name)
            if inst is not None and inst not in chain:
                chain.append(inst)

        # Filet de sécurité
        chain.append(HeuristicProvider())
        return chain

    @classmethod
    def advise(
        cls,
        *,
        context: MarketContext,
        user=None,
        portfolio=None,
        trade_idea=None,
    ) -> AIDecision:
        """
        Demande un avis avec fallback automatique. Logge la décision finale
        et toutes les tentatives échouées.
        """
        # ── Rate limiting ──────────────────────────────────────────────────────
        if not cls._check_rate_limit(user):
            limit = getattr(settings, "AI_RATE_LIMIT_PER_HOUR", cls._RATE_LIMIT_DEFAULT)
            log.warning(
                "ai_advisor.rate_limited user_id=%s symbol=%s limit=%d/h",
                getattr(user, "pk", "?"), context.symbol, limit,
            )
            decision = AIDecision(
                decision="ABSTAIN",
                confidence=0.0,
                rationale=f"Limite IA atteinte ({limit} appels/h). Réessayer dans la prochaine fenêtre.",
                risks=["rate_limit_exceeded"],
                provider="HEURISTIC",
                model_name="rate-limited",
            )
            cls._record_decision(
                decision=decision,
                context=context, user=user, portfolio=portfolio, trade_idea=trade_idea,
                fallback_used=True, fallback_reason="rate_limited",
                attempt_logs=[],
            )
            return decision

        chain = cls.get_provider_chain()
        last_error = ""
        attempt_logs = []

        for idx, provider in enumerate(chain):
            available = False
            try:
                available = provider.is_available()
            except Exception as exc:
                last_error = f"{provider.name}.is_available threw: {exc}"
                attempt_logs.append({"provider": provider.name, "skipped": True, "reason": str(exc)})
                continue

            if not available:
                attempt_logs.append({"provider": provider.name, "skipped": True, "reason": "unavailable"})
                continue

            t0 = time.monotonic()
            try:
                decision = provider.advise(context)
            except ProviderUnavailable as exc:
                last_error = f"{provider.name}: {exc}"
                latency = int((time.monotonic() - t0) * 1000)
                attempt_logs.append({
                    "provider": provider.name, "skipped": False,
                    "ok": False, "latency_ms": latency, "error": str(exc),
                })
                continue
            except Exception as exc:
                # Erreur non typée → log mais continue le fallback
                last_error = f"{provider.name} unexpected: {exc}"
                log.exception("ai_advisor.provider_unexpected provider=%s", provider.name)
                continue

            # Succès
            fallback_used = (idx > 0)
            fallback_reason = last_error[:200] if fallback_used else ""

            try:
                cls._record_decision(
                    decision=decision,
                    context=context,
                    user=user, portfolio=portfolio, trade_idea=trade_idea,
                    fallback_used=fallback_used,
                    fallback_reason=fallback_reason,
                    attempt_logs=attempt_logs,
                )
            except Exception:
                log.exception("ai_advisor.record_decision_failed")

            log.info(
                "ai_advisor.advise.ok provider=%s symbol=%s decision=%s confidence=%.2f fallback=%s",
                decision.provider, context.symbol, decision.decision,
                decision.confidence, fallback_used,
            )
            return decision

        # Tous les providers ont échoué (très improbable car heuristic est toujours dispo)
        log.error("ai_advisor.advise.all_failed last_error=%s", last_error)
        # Décision par défaut : ABSTAIN
        decision = AIDecision(
            decision="ABSTAIN",
            confidence=0.0,
            rationale=f"Tous les providers IA ont échoué: {last_error}",
            risks=["all_providers_unavailable"],
            provider="HEURISTIC",
            model_name="emergency-abstain",
        )
        cls._record_decision(
            decision=decision,
            context=context, user=user, portfolio=portfolio, trade_idea=trade_idea,
            fallback_used=True, fallback_reason="all_providers_failed",
            attempt_logs=attempt_logs, error_message=last_error,
        )
        return decision

    @staticmethod
    def _record_decision(
        *,
        decision: AIDecision,
        context: MarketContext,
        user, portfolio, trade_idea,
        fallback_used: bool,
        fallback_reason: str,
        attempt_logs: list,
        error_message: str = "",
    ):
        """
        Persiste la décision pour audit et retraining.
        Sécurité : ne stocke PAS de secrets, jamais.
        """
        # RGPD : on ne stocke PAS user_objective (données personnelles libres),
        # ni recent_candles (volume de données inutile en base).
        # On ne stocke pas non plus recent_outcomes qui peut contenir des PnL
        # détaillés par trade — déjà tracés dans les modèles Trade/Position.
        prompt_inputs = {
            "symbol": context.symbol,
            "timeframe": context.timeframe,
            "regime": context.regime,
            "direction_hint": context.direction_hint,
            "max_risk_per_trade_pct": context.max_risk_per_trade_pct,
            "max_open_positions": context.max_open_positions,
            "current_open_positions": context.current_open_positions,
            "attempt_logs": attempt_logs,
        }
        AIDecisionLog.objects.create(
            user=user,
            portfolio=portfolio,
            trade_idea=trade_idea,
            symbol=context.symbol,
            provider=decision.provider or "HEURISTIC",
            model_name=decision.model_name or "",
            fallback_used=fallback_used,
            fallback_reason=fallback_reason or "",
            decision=decision.decision,
            confidence=float(decision.confidence or 0),
            expected_rr=decision.expected_rr,
            suggested_stake=decision.suggested_stake,
            suggested_stop_loss=decision.suggested_stop_loss,
            suggested_take_profit=decision.suggested_take_profit,
            rationale=decision.rationale or "",
            risks=decision.risks or [],
            prompt_inputs=prompt_inputs,
            raw_response=decision.raw_response or {},
            latency_ms=decision.latency_ms or 0,
            tokens_in=decision.tokens_in or 0,
            tokens_out=decision.tokens_out or 0,
            cost_usd=decision.cost_usd or Decimal("0"),
            error_message=error_message[:2000] if error_message else "",
        )
