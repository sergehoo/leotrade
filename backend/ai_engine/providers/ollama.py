"""
ai_engine/providers/ollama.py
=============================

Provider Ollama (LLM local). Pas de coût, pas de network externe — idéal pour
le développement, le testing, et la souveraineté des données.

Endpoint par défaut : http://localhost:11434
Modèle conseillé : llama3:70b-instruct ou mistral-large

Configuration via settings :
  AI_OLLAMA_BASE_URL = "http://localhost:11434"
  AI_OLLAMA_MODEL    = "llama3"

Le prompt force le même schéma JSON que Claude pour interchangeabilité.
"""

from __future__ import annotations

import json
import logging
import os
import time
from decimal import Decimal

import httpx
from django.conf import settings

from .base import BaseAIProvider, MarketContext, AIDecision, ProviderUnavailable
from .claude import SYSTEM_PROMPT, _build_user_prompt, _extract_json, _parsed_to_decision


log = logging.getLogger("lyneci.ai_engine.ollama")


class OllamaProvider(BaseAIProvider):
    name = "OLLAMA"

    DEFAULT_BASE_URL = "http://localhost:11434"
    DEFAULT_MODEL = "llama3"

    def __init__(self, base_url: str | None = None, model: str | None = None, timeout: float = 60.0):
        self.base_url = (
            base_url
            or getattr(settings, "AI_OLLAMA_BASE_URL", "")
            or os.environ.get("AI_OLLAMA_BASE_URL")
            or self.DEFAULT_BASE_URL
        ).rstrip("/")
        self.model_name = (
            model
            or getattr(settings, "AI_OLLAMA_MODEL", "")
            or os.environ.get("AI_OLLAMA_MODEL")
            or self.DEFAULT_MODEL
        )
        self.timeout = timeout

    def is_available(self) -> bool:
        """
        Ping rapide : GET /api/tags pour confirmer que ollama tourne.
        Cache le résultat 30s pour éviter de pinger à chaque requête.
        """
        try:
            with httpx.Client(timeout=2.0) as client:
                r = client.get(f"{self.base_url}/api/tags")
                return r.status_code == 200
        except Exception:
            return False

    def advise(self, context: MarketContext) -> AIDecision:
        user_prompt = _build_user_prompt(context)

        # Ollama Chat API : /api/chat
        body = {
            "model": self.model_name,
            "stream": False,
            "format": "json",  # Ollama supporte un mode JSON forcé
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "options": {
                "temperature": 0.2,  # déterministe pour cas trading
                "num_predict": 768,
            },
        }
        t0 = time.monotonic()
        try:
            with httpx.Client(timeout=self.timeout) as client:
                r = client.post(f"{self.base_url}/api/chat", json=body)
                r.raise_for_status()
                data = r.json()
        except Exception as exc:
            log.exception("ollama.api_call_failed err=%s", exc)
            raise ProviderUnavailable(f"Ollama API error: {exc}") from exc

        latency_ms = int((time.monotonic() - t0) * 1000)

        try:
            raw_text = (data.get("message") or {}).get("content", "").strip()
        except Exception:
            raw_text = ""
        if not raw_text:
            raise ProviderUnavailable("Ollama a retourné une réponse vide.")

        try:
            parsed = json.loads(_extract_json(raw_text))
        except json.JSONDecodeError as exc:
            log.warning("ollama.json_parse_failed text=%r", raw_text[:300])
            raise ProviderUnavailable(f"Ollama JSON parse error: {exc}") from exc

        # Ollama renvoie eval_count / prompt_eval_count
        tokens_in = int(data.get("prompt_eval_count") or 0)
        tokens_out = int(data.get("eval_count") or 0)
        cost_usd = Decimal("0")  # local = gratuit

        return _parsed_to_decision(
            parsed,
            provider=self.name,
            model_name=self.model_name,
            raw_response={"text": raw_text, "model": self.model_name},
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
        )
