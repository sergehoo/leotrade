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
import re
import threading
import time
from decimal import Decimal

from django.conf import settings

from .base import BaseAIProvider, MarketContext, AIDecision, ProviderUnavailable


log = logging.getLogger("lyneci.ai_engine.claude")


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
7. Jamais de réponse générique : chaque champ doit citer les valeurs concrètes
   des indicateurs fournis (ex. "RSI à 28, sous la borne 30").
8. "invalidation" décrit une condition OBJECTIVE et vérifiable (niveau de prix,
   croisement d'indicateur) qui annule ton scénario principal.
9. "probability_estimate" est ta probabilité calibrée que le scénario principal
   se réalise sur l'horizon du timeframe (0.0-1.0, cohérente avec confidence).

Schéma de sortie OBLIGATOIRE :
{
  "decision": "EXECUTE" | "PLAN" | "WATCH" | "REJECT" | "ABSTAIN",
  "confidence": 0.0-1.0,
  "direction": "LONG" | "SHORT" | null,
  "expected_rr": float (R:R attendu) | null,
  "suggested_stake": float | null,
  "suggested_stop_loss": float | null,
  "suggested_take_profit": float | null,
  "rationale": "analyse détaillée en français citant les indicateurs, max 5 phrases",
  "primary_scenario": "scénario principal attendu (mouvement, cible, horizon)",
  "alternative_scenario": "scénario alternatif si le principal échoue",
  "invalidation": "condition objective qui invalide le scénario principal",
  "probability_estimate": 0.0-1.0,
  "risks": ["risque1", "risque2", ...]
}
"""


_SAFE_REGIME = re.compile(r"^[A-Za-z0-9_\- ]{0,40}$")
_SAFE_DIRECTION = re.compile(r"^(LONG|SHORT|NEUTRAL|none|aucune)?$", re.IGNORECASE)


def _sanitize_indicators(indicators: dict) -> dict:
    """
    Sécurité : ne conserver que les valeurs numériques des indicateurs.
    Tout string dans les valeurs pourrait injecter des instructions dans le
    prompt Claude — on les supprime silencieusement.
    """
    safe: dict = {}
    for k, v in (indicators or {}).items():
        # Clé : identifiant Python simple uniquement
        if not (isinstance(k, str) and re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,49}$", k)):
            continue
        if isinstance(v, bool):
            continue  # bool sous-classe de int — on l'exclut
        if isinstance(v, (int, float)):
            safe[k] = round(float(v), 8)
        elif isinstance(v, Decimal):
            safe[k] = round(float(v), 8)
        else:
            try:
                safe[k] = round(float(str(v)), 8)
            except (TypeError, ValueError):
                pass  # valeur non numérique → ignorée
    return safe


def _sanitize_candle(c) -> dict | None:
    """Sanitize a single candle dict — keep only known numeric fields."""
    if not isinstance(c, dict):
        return None
    out = {}
    for field in ("open_time", "open", "high", "low", "close", "volume"):
        if field not in c:
            continue
        v = c[field]
        if field == "open_time":
            out[field] = str(v)[:32]  # ISO string max 32 chars
        else:
            try:
                out[field] = round(float(str(v)), 8)
            except (TypeError, ValueError):
                pass
    return out or None


def _build_user_prompt(ctx: MarketContext) -> str:
    regime = (ctx.regime or "inconnu")[:40]
    if not _SAFE_REGIME.match(regime):
        regime = "inconnu"

    direction_hint = (ctx.direction_hint or "aucune")[:10]
    if not _SAFE_DIRECTION.match(direction_hint):
        direction_hint = "aucune"

    safe_indicators = _sanitize_indicators(ctx.indicators)
    safe_candles = [
        sc for c in (ctx.recent_candles[-10:] or [])
        if (sc := _sanitize_candle(c)) is not None
    ]

    return (
        f"Symbole: {ctx.symbol}\n"
        f"Timeframe: {ctx.timeframe}\n"
        f"Régime de marché: {regime}\n"
        f"Direction suggérée par le système: {direction_hint}\n"
        f"Prix actuel: {ctx.last_price}\n"
        f"\nIndicateurs techniques: {json.dumps(safe_indicators)}\n"
        f"\nDernières bougies (N={len(safe_candles)}): {json.dumps(safe_candles)}\n"
        f"\nÉtat du portefeuille:\n"
        f"- balance: {ctx.portfolio_balance}\n"
        f"- equity: {ctx.portfolio_equity}\n"
        f"- cash disponible: {ctx.available_cash}\n"
        f"- positions ouvertes: {ctx.current_open_positions}/{ctx.max_open_positions}\n"
        f"- max risque par trade: {ctx.max_risk_per_trade_pct}%\n"
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
        # Thread-local storage: each Celery worker thread gets its own client
        # instance, évitant les race conditions sur self._client partagé.
        self._local = threading.local()

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        client = getattr(self._local, "client", None)
        if client is not None:
            return client
        try:
            import anthropic  # type: ignore
        except ImportError as exc:
            raise ProviderUnavailable("SDK anthropic non installé.") from exc
        self._local.client = anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout)
        return self._local.client

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
        primary_scenario=str(parsed.get("primary_scenario", ""))[:1000],
        alternative_scenario=str(parsed.get("alternative_scenario", ""))[:1000],
        invalidation=str(parsed.get("invalidation", ""))[:500],
        probability_estimate=(
            max(0.0, min(1.0, float(parsed["probability_estimate"])))
            if parsed.get("probability_estimate") is not None
            else None
        ),
        provider=provider,
        model_name=model_name,
        raw_response=raw_response,
        latency_ms=latency_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
    )
