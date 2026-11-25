"""
AssistantIntentService — moteur d'intentions conversationnelles.

Détection DÉTERMINISTE (règles + regex FR/EN) : pour les actions sensibles,
on ne laisse pas un LLM décider seul qu'un texte ambigu est un ordre
d'exécution. Un message qui ne matche aucune règle → GENERAL_CHAT (LLM).

Chaque détection retourne aussi les ENTITÉS extraites : symbole, montant,
pourcentage, identifiants (#145), mode paper/live, périmètre (perdantes…).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class Intent:
    ASK_MARKET_OPPORTUNITY = "ASK_MARKET_OPPORTUNITY"
    EXPLAIN_TRADE_IDEA = "EXPLAIN_TRADE_IDEA"
    APPROVE_TRADE_IDEA = "APPROVE_TRADE_IDEA"
    REJECT_TRADE_IDEA = "REJECT_TRADE_IDEA"
    PREPARE_TRADE = "PREPARE_TRADE"
    CONFIRM_TRADE_EXECUTION = "CONFIRM_TRADE_EXECUTION"
    CANCEL_ACTION = "CANCEL_ACTION"
    CANCEL_ORDER = "CANCEL_ORDER"
    CLOSE_POSITION = "CLOSE_POSITION"
    REDUCE_POSITION = "REDUCE_POSITION"
    SYNC_PORTFOLIO = "SYNC_PORTFOLIO"
    TEST_BROKER = "TEST_BROKER"
    ACTIVATE_KILL_SWITCH = "ACTIVATE_KILL_SWITCH"
    DISABLE_AUTO_TRADING = "DISABLE_AUTO_TRADING"
    PORTFOLIO_ANALYSIS = "PORTFOLIO_ANALYSIS"
    RISK_ANALYSIS = "RISK_ANALYSIS"
    GENERAL_CHAT = "GENERAL_CHAT"


@dataclass
class DetectedIntent:
    intent: str
    confidence: float = 1.0
    entities: dict = field(default_factory=dict)


# ── Extraction d'entités ─────────────────────────────────────────────────────

_SYMBOL_RE = re.compile(
    r"\b("
    r"R_\d{2,3}|1HZ\d{2,3}V|BOOM\d{3,4}|CRASH\d{3,4}|JD\d{2,3}"          # Deriv
    r"|[A-Z]{3,5}USDT?|[A-Z]{3}/[A-Z]{3}|XAUUSD|EURUSD|GBPUSD|USDJPY"   # crypto / forex
    r"|BTC|ETH|SOL|XRP"
    r")\b"
)
_AMOUNT_RE = re.compile(
    r"(?:avec|de|pour|montant(?:\s+de)?|stake(?:\s+de)?|with|for)?\s*"
    r"(\d+(?:[.,]\d+)?)\s*(?:usdt?|usd|\$|dollars?)\b",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"(\d{1,3})\s*%")
_REF_ID_RE = re.compile(r"#\s?(\d+)")
_MODE_RE = re.compile(r"\b(paper|live|réel|reel|demo)\b", re.IGNORECASE)


def _extract_entities(text: str) -> dict:
    entities: dict = {}

    symbol = _SYMBOL_RE.search(text.upper())
    if symbol:
        sym = symbol.group(1)
        # Normalisation crypto courte → paire USDT
        if sym in ("BTC", "ETH", "SOL", "XRP"):
            sym = f"{sym}USDT"
        entities["symbol"] = sym

    amount = _AMOUNT_RE.search(text)
    if amount:
        entities["amount"] = float(amount.group(1).replace(",", "."))

    percent = _PERCENT_RE.search(text)
    if percent:
        entities["percent"] = min(100, int(percent.group(1)))

    ref = _REF_ID_RE.search(text)
    if ref:
        entities["ref_id"] = int(ref.group(1))

    mode = _MODE_RE.search(text)
    if mode:
        raw = mode.group(1).lower()
        entities["mode"] = "LIVE" if raw in ("live", "réel", "reel") else "PAPER"

    lowered = text.lower()
    if any(w in lowered for w in ("perdante", "perdants", "losing", "en perte")):
        entities["scope"] = "LOSING"
    if any(w in lowered for w in ("toutes", "tous", "all ")):
        entities["scope_all"] = True

    return entities


# ── Règles d'intention (ordre = priorité) ────────────────────────────────────

def _has(text: str, *fragments: str) -> bool:
    return any(f in text for f in fragments)


_DEMONSTRATIVE = ("ce trade", "cette opportunité", "cette opportunite", "cette idée",
                  "cette idee", "this trade", "this opportunity", "cet ordre")


class AssistantIntentService:
    @classmethod
    def detect(cls, text: str) -> DetectedIntent:
        raw = (text or "").strip()
        if not raw:
            return DetectedIntent(Intent.GENERAL_CHAT, 0.0)
        t = raw.lower()
        entities = _extract_entities(raw)

        # ── Confirmation / annulation d'une action en attente ────────────
        if re.fullmatch(
            r"(oui|yes|ok|go|confirme[rz]?|je confirme|oui je confirme|"
            r"valide|valider|c'est bon|vas[- ]?y|confirm|d'accord|1)\s*[.!]?",
            t,
        ):
            return DetectedIntent(Intent.CONFIRM_TRADE_EXECUTION, 1.0, entities)
        if re.fullmatch(
            r"(non|no|annule[rz]?|annule ça|cancel|stop|laisse tomber|abandonne[rz]?|2)\s*[.!]?",
            t,
        ):
            return DetectedIntent(Intent.CANCEL_ACTION, 1.0, entities)

        # ── Kill switch / auto-trading / sécurité ────────────────────────
        # "coupe tout" en frontière de mot (sinon "coupe toutes les positions"
        # serait pris pour un kill switch) ET sans mention de position
        # (→ ce serait une clôture, pas le kill switch global).
        kill_phrase = bool(re.search(r"\b(coupe|arrête|arrete|stoppe) tout\b", t)) and not _has(
            t, "position", "positions"
        )
        if _has(t, "kill switch", "killswitch") or kill_phrase:
            return DetectedIntent(Intent.ACTIVATE_KILL_SWITCH, 1.0, entities)
        if (_has(t, "désactive", "desactive", "disable", "stoppe", "arrête", "coupe")
                and _has(t, "auto-trading", "auto trading", "autotrading",
                         "trading automatique", "live trading", "le live")):
            return DetectedIntent(Intent.DISABLE_AUTO_TRADING, 1.0, entities)

        # ── Gestion ordres / positions ───────────────────────────────────
        if _has(t, "annule", "cancel") and _has(t, "ordre", "order"):
            return DetectedIntent(Intent.CANCEL_ORDER, 1.0, entities)
        if (_has(t, "réduis", "reduis", "reduce", "allège", "allege")
                and _has(t, "position", "expo")):
            return DetectedIntent(Intent.REDUCE_POSITION, 1.0, entities)
        if (_has(t, "ferme", "clôture", "cloture", "close", "coupe", "liquide")
                and _has(t, "position", "positions")):
            return DetectedIntent(Intent.CLOSE_POSITION, 1.0, entities)

        # ── Broker / portefeuille (opérations) ───────────────────────────
        if (_has(t, "synchronise", "synchro", "sync", "rafraîchis", "rafraichis")
                and _has(t, "portefeuille", "portfolio", "solde", "balance", "positions")):
            return DetectedIntent(Intent.SYNC_PORTFOLIO, 1.0, entities)
        if (_has(t, "teste", "test", "vérifie", "verifie", "check")
                and _has(t, "broker", "connexion", "deriv", "binance", "mt5")):
            return DetectedIntent(Intent.TEST_BROKER, 1.0, entities)

        # ── Cycle de vie trade idea ──────────────────────────────────────
        if (_has(t, "exécute", "execute", "lance", "prends", "ouvre", "place",
                 "prépare", "prepare", "passe")
                and (_has(t, *_DEMONSTRATIVE) or "symbol" in entities
                     or "ref_id" in entities or "amount" in entities)
                and _has(t, "trade", "ordre", "position", "opportunité", "opportunite",
                         "idée", "idee", "achat", "vente", "buy", "sell", "usdt", "usd", "$")):
            return DetectedIntent(Intent.PREPARE_TRADE, 0.95, entities)
        if _has(t, "valide", "approuve", "approve") and _has(
                t, "trade", "idée", "idee", "opportunité", "opportunite", "signal"):
            return DetectedIntent(Intent.APPROVE_TRADE_IDEA, 0.9, entities)
        if _has(t, "rejette", "refuse", "reject") and _has(
                t, "trade", "idée", "idee", "opportunité", "opportunite", "signal"):
            return DetectedIntent(Intent.REJECT_TRADE_IDEA, 0.9, entities)
        if (_has(t, "explique", "explain", "pourquoi", "détaille", "detaille")
                and _has(t, "opportunité", "opportunite", "idée", "idee", "trade idea",
                         "signal", "score")):
            return DetectedIntent(Intent.EXPLAIN_TRADE_IDEA, 0.85, entities)

        # ── Recherche d'opportunités ─────────────────────────────────────
        if (_has(t, "opportunité", "opportunite", "opportunities", "scanne", "scan",
                 "meilleures idées", "meilleures idees", "quoi trader", "que trader",
                 "des trades", "setup")
                and _has(t, "trouve", "cherche", "montre", "donne", "propose", "scan",
                         "quelles", "quoi", "que ", "y a-t-il", "best", "meilleures")):
            return DetectedIntent(Intent.ASK_MARKET_OPPORTUNITY, 0.85, entities)

        # ── Analyses (déléguées au LLM avec contexte) ────────────────────
        if _has(t, "analyse") and _has(t, "portefeuille", "portfolio", "mes positions",
                                       "mon compte", "performance"):
            return DetectedIntent(Intent.PORTFOLIO_ANALYSIS, 0.8, entities)
        if _has(t, "risque", "risk", "drawdown", "exposition") and _has(
                t, "analyse", "où en", "ou en", "quel est", "combien", "état", "etat"):
            return DetectedIntent(Intent.RISK_ANALYSIS, 0.8, entities)

        return DetectedIntent(Intent.GENERAL_CHAT, 0.0, entities)
