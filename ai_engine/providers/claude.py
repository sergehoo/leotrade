"""
ai_engine/providers/claude.py
=============================

Provider Anthropic Claude. Préféré quand `ANTHROPIC_API_KEY` est configuré.
Utilise le SDK officiel `anthropic` si disponible, sinon HTTP brut.

Le prompt force une sortie JSON stricte (parsée + validée). Si la sortie
n'est pas du JSON valide → ProviderUnavailable → fallback orchestrateur.

Coût indicatif (Claude Opus 4.5, prix mai 2025) :
  - input  : ~$15/M tokens
  - output : ~$75/M tokens
"""

from __future__ import annotations

import json
import logging
import os
import time
from decimal import Decimal

from django.conf import settings

from .base import BaseAIProvider, MarketContext, AIDecision, ProviderUnavailable


log = logging.getLogger("leotrade.ai_engine.claude")


SYSTEM_PROMPT = """Tu es un assistant trading systémique senior. Tu analyses des features
techniques (RSI, MACD, SMA, ATR, régime de marché) et tu produis une recommandation
de trade STRICTEMENT au format JSON.

Règles absolues :
1. Tu réponds UNIQUEMENT avec un objet JSON, sans texte avant ni après.
2. Tu refuses (decision="REJECT") si les conditions ne sont pas claires.
3. Tu donnes des SL/TP réalistes basés sur l'ATR (rarement plus de 3×ATR).
4. confidence ∈ [0.0, 1.0]. Sois calibré : 0.9+ uniquement si tous les signaux concordent.
5. Tu ne JAMAIS recommandes plus que max_risk_per_trade_pct du capital.
6. Tu décris les risques concrets dans "risks".

Schéma de sortie OBLIGATOIRE :
{
  "decision": "EXECUTE" | "PLAN" | "WATCH" | "REJECT" | "ABSTAIN",
  "confidence": 0.0-1.0,
  "direction": "LONG" | "SHORT" | null,
  "expected_rr": float (R:R attendu) | null,
  "suggested_stake": float | null,
  "suggested_stop_loss": float | null,
  "suggested_take_profit": float | null,
  "rationale": "explication concise en français, max 3 phrases",
  "risks": ["risque1", "risque2", ...]
}
"""


def _build_user_prompt(ctx: MarketContext) -> str:
    return (
        f"Symbole: {ctx.symbol}\n"
        f"Timeframe: {ctx.timeframe}\n"
        f"Régime de marché: {ctx.regime or 'inconnu'}\n"
        f"Direction suggérée par le système: {ctx.direction_hint or 'aucune'}\n"
        f"Prix actuel: {ctx.last_price}\n"
        f"\nIndicateurs techniques: {json.dumps(ctx.indicators, default=str)}\n"
        f"\nDernières bougies (N={len(ctx.recent_candles)}): {json.dumps(ctx.recent_candles[-10:], default=str)}\n"
        f"\nÉtat du portefeuille:\n"
        f"- balance: {ctx.portfolio_balance}\n"
        f"- equity: {ctx.portfolio_equity}\n"
        f"- cash disponible: {ctx.available_cash}\n"
        f"- positions ouvertes: {ctx.current_open_positions}/{ctx.max_open_positions}\n"
        f"- max risque par trade: {ctx.max_risk_per_trade_pct}%\n"
        f"\nObjectif utilisateur: {ctx.user_objective or '(non spécifié)'}\n"
        f"Historique récent: {ctx.recent_outcomes[-10:] if ctx.recent_outcomes else 'aucun'}\n"
        f"\nProduis ton JSON maintenant."
    )


class ClaudeProvider(BaseAIProvider):
    name = "CLAUDE"

    # Modèle par défaut. Surchargé via settings.AI_CLAUDE_MODEL.
    DEFAULT_MODEL = "claude-opus-4-5"

    # Prix indicatifs par M tokens (USD). Modifiables via settings.
    PRICE_INPUT_PER_MTOK = 15.0
    PRICE_OUTPUT_PER_MTOK = 75.0

    def __init__(self, api_key: str | None = None, model: str | None = None, timeout: float = 30.0):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY") or getattr(settings, "ANTHROPIC_API_KEY", "")
        self.model_name = (
            model
            or getattr(settings, "AI_CLAUDE_MODEL", "")
            or os.environ.get("AI_CLAUDE_MODEL")
            or self.DEFAULT_MODEL
        )
        self.timeout = timeout
        self._client = None

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import anthropic  # type: ignore
        except ImportError as exc:
            raise ProviderUnavailable("SDK anthropic non installé.") from exc
        self._client = anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout)
        return self._client

    def advise(self, context: MarketContext) -> AIDecision:
        if not self.is_available():
            raise ProviderUnavailable("ANTHROPIC_API_KEY manquant.")

        client = self._get_client()
        user_prompt = _build_user_prompt(context)
        t0 = time.monotonic()

        try:
            resp = client.messages.create(
                model=self.model_name,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except Exception as exc:
            log.exception("claude.api_call_failed err=%s", exc)
            raise ProviderUnavailable(f"Claude API error: {exc}") from exc

        latency_ms = int((time.monotonic() - t0) * 1000)

        # Extraction du texte
        try:
            text_blocks = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
            raw_text = "".join(text_blocks).strip()
        except Exception:
            raw_text = ""

        if not raw_text:
            raise ProviderUnavailable("Claude a retourné une réponse vide.")

        # Parse JSON
        try:
            parsed = json.loads(_extract_json(raw_text))
        except json.JSONDecodeError as exc:
            log.warning("claude.json_parse_failed text=%r", raw_text[:300])
            raise ProviderUnavailable(f"Claude JSON parse error: {exc}") from exc

        # Tokens & coût
        usage = getattr(resp, "usage", None)
        tokens_in = getattr(usage, "input_tokens", 0) if usage else 0
        tokens_out = getattr(usage, "output_tokens", 0) if usage else 0
        cost_usd = Decimal(str(
            (tokens_in / 1_000_000.0) * self.PRICE_INPUT_PER_MTOK
            + (tokens_out / 1_000_000.0) * self.PRICE_OUTPUT_PER_MTOK
        )).quantize(Decimal("0.000001"))

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


def _extract_json(text: str) -> str:
    """
    Extrait un objet JSON depuis le texte du LLM, en retirant les fences ```json
    et autres préfixes éventuels.
    """
    s = text.strip()
    # retire fences markdown
    if s.startswith("```"):
        # supprime la première ligne (```json ou ```)
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1:]
        if s.endswith("```"):
            s = s[: -3]
    s = s.strip()
    # garde uniquement le premier {...}
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        return s[start:end + 1]
    return s


def _parsed_to_decision(
    parsed: dict,
    *, provider: str, model_name: str,
    raw_response: dict, latency_ms: int,
    tokens_in: int, tokens_out: int, cost_usd: Decimal,
) -> AIDecision:
    """
    Convertit dict parsé → AIDecision typé (et validé).
    """
    def _to_dec(v):
        if v is None: return None
        try: return Decimal(str(v))
        except Exception: return None

    decision = str(parsed.get("decision", "ABSTAIN")).upper()
    if decision not in ("EXECUTE", "PLAN", "WATCH", "REJECT", "ABSTAIN"):
        decision = "ABSTAIN"

    direction = parsed.get("direction")
    if direction:
        direction = str(direction).upper()
        if direction not in ("LONG", "SHORT"):
            direction = None

    risks = parsed.get("risks") or []
    if not isinstance(risks, list):
        risks = [str(risks)]

    return AIDecision(
        decision=decision,
        confidence=float(parsed.get("confidence", 0) or 0),
        direction=direction,
        expected_rr=parsed.get("expected_rr"),
        suggested_stake=_to_dec(parsed.get("suggested_stake")),
        suggested_stop_loss=_to_dec(parsed.get("suggested_stop_loss")),
        suggested_take_profit=_to_dec(parsed.get("suggested_take_profit")),
        rationale=str(parsed.get("rationale", ""))[:2000],
        risks=[str(r) for r in risks][:10],
        provider=provider,
        model_name=model_name,
        raw_response=raw_response,
        latency_ms=latency_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
    )
