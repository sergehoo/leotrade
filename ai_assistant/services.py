"""
ai_assistant/services.py
========================

Couche service du panel IA conversationnel.

AssistantContextService  — construit le snapshot live (portfolio, risque, marché)
AssistantStreamService   — appelle les providers LLM avec streaming SSE/SDK
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from decimal import Decimal
from typing import AsyncIterator

from asgiref.sync import sync_to_async
from django.conf import settings

log = logging.getLogger("leotrade.ai_assistant")

# ── Prompt système du panel IA ─────────────────────────────────────────────────

ASSISTANT_SYSTEM_PROMPT = """Tu es LeoAI, l'assistant IA central de LeoTrade — plateforme de trading assistée par IA.

TON RÔLE :
• Assistant pédagogique et copilote de trading
• Moteur d'analyse et conseiller de risque
• Explication des décisions IA et des scores d'opportunités
• Aide à la validation et au sizing des trades

DONNÉES EN TEMPS RÉEL :
À chaque message tu reçois un snapshot live : portefeuille, positions, risque, signaux.
Utilise ces données chiffrées pour des réponses précises. Ne dis jamais "je n'ai pas accès".

RÈGLES ABSOLUES :
✅ Tu PEUX : analyser, expliquer, recommander, proposer des drafts, calculer des tailles
❌ Tu ne PEUX JAMAIS : exécuter un ordre sans confirmation explicite de l'utilisateur
❌ Tu ne PEUX JAMAIS : accéder à des plateformes ou APIs extérieures à LeoTrade
❌ Tu ne PEUX JAMAIS : contourner les validations du moteur de risque

PROPOSER UNE ACTION :
Si tu veux proposer une action concrète (draft d'ordre, ajustement SL/TP, suggestion taille),
intègre un bloc JSON entre les marqueurs <<<ACTION>>> et <<<END_ACTION>>> :
<<<ACTION>>>
{"type":"DRAFT_ORDER","symbol":"R_75","side":"BUY","size":0.35,"stop_loss":18.0,"take_profit":54.0,"rationale":"Signal fort avec momentum confirmé"}
<<<END_ACTION>>>

Types d'actions disponibles : DRAFT_ORDER | ADJUST_SL | ADJUST_TP | SUGGEST_SIZE | INFO

STYLE DE RÉPONSE :
- Réponds en français (sauf si l'utilisateur écrit en anglais)
- Sois précis avec des données chiffrées quand disponibles
- Structure tes réponses longues avec des sections
- Ton format préféré pour une analyse complète :
  **Contexte** → situation marché
  **Analyse** → indicateurs, tendance, momentum
  **Risques** → points d'attention
  **Conseil IA** → synthèse actionnable"""

# ── Marqueurs d'actions ────────────────────────────────────────────────────────

_ACTION_RE = re.compile(
    r"<<<ACTION>>>\s*(.*?)\s*<<<END_ACTION>>>",
    re.DOTALL,
)


def extract_actions(text: str) -> tuple[str, list[dict]]:
    """
    Extrait les blocs <<<ACTION>>>...<<<END_ACTION>>> du texte.
    Retourne (texte_nettoyé, liste_d_actions).
    """
    actions = []
    for match in _ACTION_RE.finditer(text):
        try:
            action = json.loads(match.group(1))
            if isinstance(action, dict) and "type" in action:
                actions.append(action)
        except (json.JSONDecodeError, ValueError):
            pass
    clean = _ACTION_RE.sub("", text).strip()
    return clean, actions


# ── Context builder ────────────────────────────────────────────────────────────

class AssistantContextService:
    """
    Construit le snapshot live injecté dans chaque prompt assistant.
    Tous les appels DB sont synchrones — à appeler via sync_to_async.
    """

    @staticmethod
    def build(user, portfolio=None, extra: dict | None = None) -> dict:
        ctx: dict = {
            "user": str(user),
            "portfolio": None,
            "positions": [],
            "risk": {},
            "recent_signals": [],
            "opportunity": None,
        }

        # ── Portefeuille ──────────────────────────────────────────────────────
        if portfolio is None:
            try:
                from portfolio.models import Portfolio
                portfolio = (
                    Portfolio.objects
                    .filter(user=user, is_active=True)
                    .select_related("broker_account")
                    .order_by("-is_default")
                    .first()
                )
            except Exception:
                portfolio = None

        if portfolio:
            ctx["portfolio"] = {
                "id": portfolio.id,
                "name": portfolio.name,
                "balance": str(getattr(portfolio, "balance", 0) or 0),
                "equity": str(getattr(portfolio, "equity", 0) or 0),
                "available_cash": str(getattr(portfolio, "available_cash", 0) or 0),
                "drawdown_pct": str(getattr(portfolio, "current_drawdown_percent", 0) or 0),
                "max_drawdown_pct": str(getattr(portfolio, "max_drawdown_percent", 0) or 0),
                "broker": getattr(getattr(portfolio, "broker_account", None), "name", ""),
                "mode": getattr(getattr(portfolio, "broker_account", None), "mode", "PAPER"),
            }

            # ── Positions ouvertes ─────────────────────────────────────────
            try:
                positions = (
                    portfolio.positions
                    .filter(status__in=["OPEN", "PARTIALLY_CLOSED"])
                    .values("id", "symbol", "side", "quantity", "entry_price",
                            "current_price", "pnl", "pnl_percent")[:10]
                )
                ctx["positions"] = [
                    {
                        "symbol": p["symbol"],
                        "side": p["side"],
                        "qty": str(p["quantity"] or 0),
                        "entry": str(p["entry_price"] or 0),
                        "current": str(p["current_price"] or 0),
                        "pnl": str(p["pnl"] or 0),
                        "pnl_pct": str(round(float(p["pnl_percent"] or 0), 2)),
                    }
                    for p in positions
                ]
            except Exception:
                pass

            # ── État risque ───────────────────────────────────────────────
            try:
                from risk.models import RiskProfile, KillSwitch
                profile = (
                    RiskProfile.objects
                    .filter(portfolio=portfolio)
                    .order_by("-is_default")
                    .first()
                )
                kill_switch = (
                    KillSwitch.objects
                    .filter(portfolio=portfolio, is_active=True)
                    .first()
                )
                ctx["risk"] = {
                    "max_risk_per_trade": str(getattr(profile, "max_risk_per_trade", 2) or 2),
                    "max_daily_drawdown": str(getattr(profile, "max_daily_drawdown", 5) or 5),
                    "max_open_positions": int(getattr(profile, "max_open_positions", 10) or 10),
                    "open_positions_count": len(ctx["positions"]),
                    "kill_switch_active": kill_switch is not None,
                    "kill_switch_reason": getattr(kill_switch, "reason", "") if kill_switch else "",
                }
            except Exception:
                ctx["risk"] = {}

        # ── Signaux récents ───────────────────────────────────────────────────
        try:
            from trading.models_ai import TradeRecommendation
            signals = (
                TradeRecommendation.objects
                .filter(user=user, status__in=["PENDING", "APPROVED"])
                .select_related("opportunity")
                .order_by("-created_at")[:5]
            )
            ctx["recent_signals"] = [
                {
                    "id": s.id,
                    "symbol": getattr(s.opportunity, "symbol", "?"),
                    "direction": getattr(s.opportunity, "direction", "?"),
                    "confidence": str(getattr(s, "ai_confidence", 0) or 0),
                    "status": s.status,
                }
                for s in signals
            ]
        except Exception:
            pass

        # ── Opportunité spécifique (si demandée via extra) ────────────────────
        opp_id = (extra or {}).get("opportunity_id")
        if opp_id:
            try:
                from trading.models_ai import MarketOpportunity
                opp = MarketOpportunity.objects.filter(pk=opp_id).first()
                if opp:
                    ctx["opportunity"] = {
                        "id": opp.id,
                        "symbol": getattr(opp, "symbol", "?"),
                        "direction": getattr(opp, "direction", "?"),
                        "score": str(getattr(opp, "score", 0) or 0),
                        "confidence": str(getattr(opp, "confidence", 0) or 0),
                        "risk_reward": str(getattr(opp, "risk_reward", 0) or 0),
                        "timeframe": getattr(opp, "timeframe_code", "?"),
                        "indicators": getattr(opp, "features", {}) or {},
                        "summary": getattr(opp, "ai_summary", "") or "",
                        "risks": getattr(opp, "risks", []) or [],
                    }
            except Exception:
                pass

        return ctx


def _format_context_for_prompt(ctx: dict) -> str:
    """Sérialise le contexte live en texte structuré pour le prompt."""
    lines = ["=== CONTEXTE LIVE LEOTRADE ==="]

    p = ctx.get("portfolio")
    if p:
        lines += [
            f"\nPORTEFEUILLE : {p['name']} ({p['mode']})",
            f"  Balance: {p['balance']} | Equity: {p['equity']} | Cash dispo: {p['available_cash']}",
            f"  Drawdown actuel: {p['drawdown_pct']}% / max autorisé: {p['max_drawdown_pct']}%",
        ]
    else:
        lines.append("\nPORTEFEUILLE : non sélectionné")

    r = ctx.get("risk", {})
    if r:
        ks = " ⚠️ KILL SWITCH ACTIF" if r.get("kill_switch_active") else ""
        lines += [
            f"\nRISQUE :{ks}",
            f"  Max risque/trade: {r.get('max_risk_per_trade')}% | Max drawdown/jour: {r.get('max_daily_drawdown')}%",
            f"  Positions: {r.get('open_positions_count')}/{r.get('max_open_positions')}",
        ]

    positions = ctx.get("positions", [])
    if positions:
        lines.append(f"\nPOSITIONS OUVERTES ({len(positions)}) :")
        for pos in positions:
            sign = "+" if float(pos["pnl"] or 0) >= 0 else ""
            lines.append(
                f"  {pos['symbol']} {pos['side']} qty={pos['qty']} "
                f"entrée={pos['entry']} actuel={pos['current']} "
                f"P&L={sign}{pos['pnl']} ({sign}{pos['pnl_pct']}%)"
            )
    else:
        lines.append("\nPOSITIONS : aucune position ouverte")

    signals = ctx.get("recent_signals", [])
    if signals:
        lines.append(f"\nSIGNAUX IA RÉCENTS ({len(signals)}) :")
        for s in signals:
            lines.append(
                f"  #{s['id']} {s['symbol']} {s['direction']} "
                f"confiance={s['confidence']} [{s['status']}]"
            )

    opp = ctx.get("opportunity")
    if opp:
        lines += [
            f"\nOPPORTUNITÉ ANALYSÉE : #{opp['id']} {opp['symbol']} {opp['direction']} ({opp['timeframe']})",
            f"  Score={opp['score']} | Confiance={opp['confidence']} | R/R={opp['risk_reward']}",
        ]
        inds = opp.get("indicators", {})
        if inds:
            ind_str = " | ".join(
                f"{k}={round(float(v), 2)}" for k, v in list(inds.items())[:8]
                if v is not None
            )
            lines.append(f"  Indicateurs: {ind_str}")
        if opp.get("summary"):
            lines.append(f"  Résumé IA: {opp['summary'][:200]}")
        if opp.get("risks"):
            lines.append(f"  Risques: {', '.join(opp['risks'][:3])}")

    lines.append("\n=== FIN CONTEXTE ===")
    return "\n".join(lines)


# ── Streaming LLM ──────────────────────────────────────────────────────────────

class AssistantStreamService:
    """
    Appelle les providers IA avec streaming token-par-token.
    Chaîne : DeepSeek → Claude → Heuristic (non streamé).
    """

    @staticmethod
    async def stream(
        messages: list[dict],
        system_prompt: str,
    ) -> AsyncIterator[str]:
        """
        Générateur asynchrone qui yield des chunks de texte.
        Essaie DeepSeek en premier, puis Claude, puis heuristic synthétique.
        En cas d'échec, les erreurs réelles sont surfacées à l'utilisateur.
        """
        primary = getattr(settings, "AI_PRIMARY_PROVIDER", "DEEPSEEK").upper()
        secondary = getattr(settings, "AI_SECONDARY_PROVIDER", "CLAUDE").upper()

        provider_errors: dict[str, str] = {}

        for provider_name in (primary, secondary):
            try:
                async for chunk in AssistantStreamService._try_provider(
                    provider_name, messages, system_prompt
                ):
                    yield chunk
                return  # success — stop here
            except Exception as exc:
                err_msg = str(exc)
                provider_errors[provider_name] = err_msg
                log.warning(
                    "assistant.stream.provider_failed provider=%s err=%s",
                    provider_name,
                    err_msg,
                )

        # Les deux LLMs ont échoué — construire un message de diagnostic avant le fallback
        async for chunk in AssistantStreamService._heuristic_response(
            messages, provider_errors=provider_errors
        ):
            yield chunk

    @staticmethod
    async def _try_provider(
        name: str,
        messages: list[dict],
        system_prompt: str,
    ) -> AsyncIterator[str]:
        if name == "DEEPSEEK":
            async for chunk in AssistantStreamService._stream_deepseek(messages, system_prompt):
                yield chunk
        elif name == "CLAUDE":
            async for chunk in AssistantStreamService._stream_claude(messages, system_prompt):
                yield chunk
        else:
            async for chunk in AssistantStreamService._heuristic_response(messages):
                yield chunk

    # ── DeepSeek streaming ─────────────────────────────────────────────────────

    @staticmethod
    async def _stream_deepseek(
        messages: list[dict],
        system_prompt: str,
    ) -> AsyncIterator[str]:
        import httpx

        api_key = (
            os.environ.get("DEEPSEEK_API_KEY")
            or getattr(settings, "DEEPSEEK_API_KEY", "")
        )
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY manquant")

        model = getattr(settings, "AI_DEEPSEEK_MODEL", "deepseek-chat")
        base_url = getattr(settings, "AI_DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        is_reasoner = "reasoner" in model.lower()

        body = {
            "model": model,
            "stream": True,
            "temperature": 0.4 if not is_reasoner else 1.0,
            "max_tokens": 2048,
            "messages": [{"role": "system", "content": system_prompt}] + messages,
        }
        if not is_reasoner:
            body["response_format"] = {"type": "text"}

        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{base_url}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {api_key}"},
            ) as response:
                if response.status_code == 401:
                    raise ValueError("DeepSeek 401 — clé API invalide")
                if response.status_code == 402:
                    raise ValueError("DeepSeek 402 — solde insuffisant")
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        data = json.loads(payload)
                        delta = data["choices"][0]["delta"]
                        # Pour R1 : skip reasoning_content, yield content seulement
                        text = delta.get("content") or ""
                        if text:
                            yield text
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

    # ── Claude streaming ───────────────────────────────────────────────────────

    @staticmethod
    async def _stream_claude(
        messages: list[dict],
        system_prompt: str,
    ) -> AsyncIterator[str]:
        api_key = (
            os.environ.get("ANTHROPIC_API_KEY")
            or getattr(settings, "ANTHROPIC_API_KEY", "")
        )
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY manquant")

        try:
            import anthropic
        except ImportError as exc:
            raise ValueError("SDK anthropic non installé") from exc

        model = getattr(settings, "AI_CLAUDE_MODEL", "claude-opus-4-5")
        client = anthropic.AsyncAnthropic(api_key=api_key)

        async with client.messages.stream(
            model=model,
            max_tokens=2048,
            system=system_prompt,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text

    # ── Heuristic (non streamé — simulé chunk par chunk) ──────────────────────

    @staticmethod
    async def _heuristic_response(
        messages: list[dict],
        provider_errors: dict[str, str] | None = None,
    ) -> AsyncIterator[str]:
        """
        Réponse déterministe basique quand aucun LLM n'est disponible.
        Lorsque provider_errors est fourni, affiche un diagnostic précis des échecs.
        """
        import asyncio

        # ── Construire le message de diagnostic ──────────────────────────────
        lines: list[str] = []

        if provider_errors:
            lines.append("⚠️ **Les moteurs IA sont temporairement indisponibles.**\n")
            lines.append("**Détail des erreurs :**\n")
            for provider, err in provider_errors.items():
                icon = "🔴"
                # Enrichir le message selon le type d'erreur
                if "402" in err or "solde insuffisant" in err.lower():
                    detail = (
                        f"{icon} **{provider}** — Solde insuffisant (402).\n"
                        f"  → Rechargez votre compte sur "
                        f"[platform.deepseek.com](https://platform.deepseek.com/top_up)\n"
                    )
                elif "401" in err or "invalide" in err.lower():
                    detail = (
                        f"{icon} **{provider}** — Clé API invalide (401).\n"
                        f"  → Vérifiez `{provider}_API_KEY` dans votre fichier `.env`\n"
                    )
                elif "manquant" in err.lower() or "missing" in err.lower():
                    # Mapper le nom provider vers la vraie variable d'environnement
                    env_var_map = {
                        "DEEPSEEK": "DEEPSEEK_API_KEY",
                        "CLAUDE": "ANTHROPIC_API_KEY",
                    }
                    env_var = env_var_map.get(provider, f"{provider}_API_KEY")
                    detail = (
                        f"{icon} **{provider}** — Clé API absente.\n"
                        f"  → Ajoutez `{env_var}=<votre_clé>` dans `.env`\n"
                    )
                elif "429" in err or "rate" in err.lower():
                    detail = (
                        f"{icon} **{provider}** — Quota dépassé (429). Réessayez dans quelques instants.\n"
                    )
                elif "non installé" in err.lower() or "importerror" in err.lower():
                    detail = (
                        f"{icon} **{provider}** — SDK non installé.\n"
                        f"  → `pip install anthropic` ou `pip install httpx`\n"
                    )
                else:
                    detail = f"{icon} **{provider}** — {err}\n"
                lines.append(detail)

            lines.append(
                "\n---\n"
                "En attendant, je peux vous aider avec les données locales :\n"
                "• Consulter vos **positions** et votre **portefeuille**\n"
                "• Vérifier l'état du **moteur de risque**\n"
                "• Accéder aux **signaux IA actifs**\n"
            )
        else:
            # Fallback générique (ne devrait pas arriver)
            lines.append(
                "Je suis temporairement en mode dégradé (LLMs indisponibles).\n\n"
                "Je peux toujours vous aider à :\n"
                "• Consulter vos positions et votre portefeuille\n"
                "• Vérifier l'état du moteur de risque\n"
                "• Accéder aux signaux IA actifs\n\n"
                "Veuillez réessayer dans quelques instants pour une analyse complète."
            )

        response = "".join(lines)

        # Simulation de streaming chunk par chunk
        words = response.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
            if i % 5 == 0:
                await asyncio.sleep(0.02)
