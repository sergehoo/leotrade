"""
ai_engine/providers/deepseek.py
================================

Provider DeepSeek (API cloud). Compatible avec deux modèles :

  • deepseek-chat     → DeepSeek-V3 : rapide, low-cost, bonne qualité
  • deepseek-reasoner → DeepSeek-R1 : chain-of-thought, très précis sur les
                        analyses multi-indicateurs (mais plus lent + cher)

L'API est 100 % OpenAI-compatible (POST /chat/completions + Bearer token).
On utilise httpx directement — aucune dépendance supplémentaire.

Configuration via settings (ou variables d'environnement) :
    DEEPSEEK_API_KEY       = "sk-..."
    AI_DEEPSEEK_MODEL      = "deepseek-chat"      # défaut
    AI_DEEPSEEK_BASE_URL   = "https://api.deepseek.com"  # optionnel
    AI_DEEPSEEK_TIMEOUT    = 60.0                 # secondes

Tarifs indicatifs (mai 2025, USD/M tokens) :
  deepseek-chat     : input 0.27 / output 1.10 (cache hit input 0.07)
  deepseek-reasoner : input 0.55 / output 2.19 (cache hit input 0.14)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from decimal import Decimal

import httpx
from django.conf import settings

from .base import BaseAIProvider, MarketContext, AIDecision, ProviderUnavailable
from .claude import SYSTEM_PROMPT, _build_user_prompt, _extract_json, _parsed_to_decision


log = logging.getLogger("leotrade.ai_engine.deepseek")

# Erreurs HTTP DeepSeek → levées comme ProviderUnavailable pour déclencher le fallback
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# Tarifs par M tokens
_PRICING: dict[str, dict[str, float]] = {
    "deepseek-chat": {
        "input": 0.27,
        "output": 1.10,
        "input_cache_hit": 0.07,
    },
    "deepseek-reasoner": {
        "input": 0.55,
        "output": 2.19,
        "input_cache_hit": 0.14,
    },
}


class DeepSeekProvider(BaseAIProvider):
    name = "DEEPSEEK"

    DEFAULT_BASE_URL = "https://api.deepseek.com"
    DEFAULT_MODEL = "deepseek-chat"
    DEFAULT_TIMEOUT = 60.0

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ):
        self.api_key = (
            api_key
            or os.environ.get("DEEPSEEK_API_KEY")
            or getattr(settings, "DEEPSEEK_API_KEY", "")
        )
        self.model_name = (
            model
            or getattr(settings, "AI_DEEPSEEK_MODEL", "")
            or os.environ.get("AI_DEEPSEEK_MODEL")
            or self.DEFAULT_MODEL
        )
        self.base_url = (
            base_url
            or getattr(settings, "AI_DEEPSEEK_BASE_URL", "")
            or os.environ.get("AI_DEEPSEEK_BASE_URL")
            or self.DEFAULT_BASE_URL
        ).rstrip("/")
        self.timeout = float(
            timeout
            or getattr(settings, "AI_DEEPSEEK_TIMEOUT", self.DEFAULT_TIMEOUT)
        )
        # Thread-local : chaque worker Celery a son propre client httpx
        self._local = threading.local()

    # ──────────────────────────────────────────────────────────────────────────
    # Internals
    # ──────────────────────────────────────────────────────────────────────────

    def _get_client(self) -> httpx.Client:
        client: httpx.Client | None = getattr(self._local, "client", None)
        if client is not None and not client.is_closed:
            return client
        self._local.client = httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        return self._local.client

    def _compute_cost(self, model: str, tokens_in: int, tokens_out: int, cache_hit_tokens: int = 0) -> Decimal:
        """Calcule le coût estimé en USD selon le modèle et le nombre de tokens."""
        pricing = _PRICING.get(model) or _PRICING.get("deepseek-chat")
        cost = (
            (tokens_in - cache_hit_tokens) / 1_000_000.0 * pricing["input"]
            + cache_hit_tokens / 1_000_000.0 * pricing.get("input_cache_hit", pricing["input"])
            + tokens_out / 1_000_000.0 * pricing["output"]
        )
        return Decimal(str(cost)).quantize(Decimal("0.000001"))

    # ──────────────────────────────────────────────────────────────────────────
    # BaseAIProvider interface
    # ──────────────────────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        return bool(self.api_key)

    def advise(self, context: MarketContext) -> AIDecision:
        if not self.is_available():
            raise ProviderUnavailable("DEEPSEEK_API_KEY manquant.")

        user_prompt = _build_user_prompt(context)
        is_reasoner = "reasoner" in self.model_name.lower()

        # deepseek-reasoner ne supporte pas response_format JSON (déjà géré
        # par le prompt SYSTEM). deepseek-chat le supporte et garantit du JSON.
        body: dict = {
            "model": self.model_name,
            "stream": False,
            "temperature": 0.0 if not is_reasoner else 1.0,  # R1 : temperature fixée à 1
            "max_tokens": 2048 if is_reasoner else 1024,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        }
        if not is_reasoner:
            body["response_format"] = {"type": "json_object"}

        client = self._get_client()
        t0 = time.monotonic()

        try:
            response = client.post("/chat/completions", json=body)
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(f"DeepSeek timeout après {self.timeout}s: {exc}") from exc
        except httpx.RequestError as exc:
            raise ProviderUnavailable(f"DeepSeek réseau erreur: {exc}") from exc

        latency_ms = int((time.monotonic() - t0) * 1000)

        # Gestion des erreurs HTTP
        if response.status_code in _RETRYABLE_STATUS:
            retry_after = int(response.headers.get("Retry-After", "5"))
            msg = f"DeepSeek HTTP {response.status_code}"
            try:
                payload = response.json()
                msg = f"{msg}: {payload.get('error', {}).get('message', response.text[:200])}"
            except Exception:
                msg = f"{msg}: {response.text[:200]}"
            raise ProviderUnavailable(msg)

        if response.status_code == 402:
            raise ProviderUnavailable("DeepSeek 402 : solde insuffisant sur le compte.")

        if response.status_code == 401:
            raise ProviderUnavailable("DeepSeek 401 : clé API invalide ou expirée.")

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProviderUnavailable(f"DeepSeek HTTP error {response.status_code}: {exc}") from exc

        try:
            data = response.json()
        except Exception as exc:
            raise ProviderUnavailable(f"DeepSeek réponse non-JSON: {exc}") from exc

        # Extraction du texte de la réponse
        # deepseek-reasoner : choice.message.reasoning_content (CoT) + content (JSON)
        # deepseek-chat     : choice.message.content (JSON direct)
        try:
            choice = data["choices"][0]["message"]
            raw_text = (choice.get("content") or "").strip()
            reasoning = (choice.get("reasoning_content") or "").strip()
        except (KeyError, IndexError) as exc:
            raise ProviderUnavailable(f"DeepSeek réponse malformée: {data}") from exc

        if not raw_text:
            raise ProviderUnavailable("DeepSeek a retourné un contenu vide.")

        log.debug(
            "deepseek.raw_response model=%s latency_ms=%d text=%r",
            self.model_name, latency_ms, raw_text[:200],
        )

        # Parse JSON
        try:
            parsed = json.loads(_extract_json(raw_text))
        except json.JSONDecodeError as exc:
            log.warning("deepseek.json_parse_failed text=%r", raw_text[:300])
            raise ProviderUnavailable(f"DeepSeek JSON parse error: {exc}") from exc

        # Tokens & coût
        usage = data.get("usage") or {}
        tokens_in = int(usage.get("prompt_tokens") or 0)
        tokens_out = int(usage.get("completion_tokens") or 0)
        # DeepSeek expose les tokens mis en cache (context caching)
        cache_hit_tokens = int(
            (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        )
        cost_usd = self._compute_cost(self.model_name, tokens_in, tokens_out, cache_hit_tokens)

        raw_response = {
            "text": raw_text,
            "model": self.model_name,
        }
        if reasoning:
            # Conserver le raisonnement R1 dans le log brut (valeur pour le retraining)
            raw_response["reasoning"] = reasoning[:4000]

        return _parsed_to_decision(
            parsed,
            provider=self.name,
            model_name=self.model_name,
            raw_response=raw_response,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
        )
