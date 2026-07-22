"""
AssistantToolRegistry — outils backend internes de l'assistant.

Deux familles :
  - LECTURE (find_trade_ideas, explain_trade_idea, analyze_*) : exécution
    immédiate, réponse markdown construite sur les données réelles.
  - ACTION  (prepare/confirm/cancel/close/reduce/sync/test/kill switch…) :
    JAMAIS d'exécution directe — création d'une AssistantActionRequest
    (garde-fous + aperçu Risk Engine + résumé), confirmation explicite
    requise (double en LIVE).

Contrat d'un tool : fn(user, conversation, entities: dict) -> dict
  {"ok": bool, "reply": str (markdown), "action_request": dict|None,
   "data": dict}
"""

from __future__ import annotations

import logging
from decimal import Decimal

from .services_actions import AssistantActionService
from .services_guards import AssistantRiskValidationService

log = logging.getLogger("lyneci.ai_assistant.tools")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de résolution
# ─────────────────────────────────────────────────────────────────────────────

def _default_portfolio(user):
    from portfolio.models import Portfolio
    return (
        Portfolio.objects.filter(user=user, is_active=True)
        .select_related("broker_account")
        .order_by("-is_default").first()
    )


def _resolve_idea(user, entities: dict, conversation=None):
    """ref_id (#145) > symbole > dernière idée actionnable de l'utilisateur."""
    from trading.models import TradeIdea

    qs = TradeIdea.objects.filter(user=user).select_related("asset", "timeframe")
    ref_id = entities.get("ref_id")
    if ref_id:
        return qs.filter(pk=ref_id).first()
    actionable = qs.filter(status__in=["NEW", "REVIEW", "APPROVED"])
    symbol = entities.get("symbol")
    if symbol:
        match = actionable.filter(symbol__iexact=symbol).order_by("-created_at").first()
        if match:
            return match
    # Contexte conversationnel : idée attachée à la conversation
    if conversation is not None and conversation.context_type == "TRADE_IDEA":
        match = qs.filter(pk=conversation.context_id).first()
        if match:
            return match
    return actionable.order_by("-overall_score", "-created_at").first()


def _idea_line(idea) -> str:
    rr = f"{idea.expected_rr:.2f}" if idea.expected_rr else "—"
    return (
        f"| #{idea.id} {idea.direction} **{idea.symbol}** | {idea.entry_price} "
        f"| {idea.stop_loss or '—'} | {idea.take_profit or '—'} | {rr} "
        f"| {idea.confidence_score:.2f} | **{idea.overall_score:.2f}** |"
    )


_IDEAS_TABLE_HEADER = (
    "| Idée | Entrée | Stop loss | Take profit | R/R | Confiance | Score |\n"
    "|---|---|---|---|---|---|---|"
)


# ─────────────────────────────────────────────────────────────────────────────
# Tools LECTURE
# ─────────────────────────────────────────────────────────────────────────────

def find_trade_ideas(user, conversation, entities):
    """Scan à la demande + meilleures opportunités selon le profil réel."""
    from trading.models import TradeIdea
    from trading.services.trade_idea_generation import TradeIdeaGenerationService

    # Scan frais (réel) — s'il échoue on retombe sur les idées récentes en base
    scan_error = ""
    try:
        TradeIdeaGenerationService.generate(
            timeframe_code=str(entities.get("timeframe") or "5m"), user=user,
        )
    except Exception as exc:
        scan_error = str(exc)[:160]
        log.warning("tools.find_trade_ideas.scan_failed err=%s", exc)

    qs = (
        TradeIdea.objects.filter(user=user, status__in=["NEW", "REVIEW", "APPROVED"])
        .order_by("-overall_score", "-created_at")
    )
    if entities.get("symbol"):
        qs = qs.filter(symbol__iexact=entities["symbol"])
    ideas = list(qs[:5])

    if not ideas:
        # Zéro fake data : on refuse de recommander sans données suffisantes
        reply = (
            "Je n'ai **aucune opportunité fiable** à te proposer maintenant"
            + (f" (scan indisponible : {scan_error})" if scan_error else "")
            + ".\n\nJe préfère ne rien recommander que te pousser un signal "
              "de mauvaise qualité — le moteur ne retient que les setups "
              "avec un score ≥ 0,65. Relance-moi dans quelques minutes."
        )
        return {"ok": True, "reply": reply, "action_request": None, "data": {"ideas": []}}

    portfolio = _default_portfolio(user)
    cash = f"{portfolio.available_cash:.2f} $" if portfolio else "—"
    rows = "\n".join(_idea_line(i) for i in ideas)
    reply = (
        f"## Meilleures opportunités du moment\n\n"
        f"{_IDEAS_TABLE_HEADER}\n{rows}\n\n"
        f"Cash disponible : **{cash}**. "
        f"Dis-moi « explique #ID » pour le raisonnement détaillé, ou "
        f"« exécute #{ideas[0].id} avec X USDT » pour préparer le meilleur setup."
    )
    return {"ok": True, "reply": reply, "action_request": None,
            "data": {"ideas": [i.id for i in ideas]}}


def explain_trade_idea(user, conversation, entities):
    idea = _resolve_idea(user, entities, conversation)
    if idea is None:
        return {"ok": False, "action_request": None, "data": {},
                "reply": "Je ne trouve pas d'idée correspondante. Donne-moi son numéro (#145) ou son symbole."}

    feats = idea.features_snapshot or {}
    feat_lines = "\n".join(
        f"- {k} : `{v}`" for k, v in list(feats.items())[:8]
    ) or "- (features non disponibles)"
    reply = (
        f"## Pourquoi {idea.direction} {idea.symbol} (#{idea.id})\n\n"
        f"{_IDEAS_TABLE_HEADER}\n{_idea_line(idea)}\n\n"
        f"**Lecture des scores** : setup {idea.setup_score:.2f} · "
        f"risque {idea.risk_score:.2f} · reward {idea.reward_score:.2f} → "
        f"score global **{idea.overall_score:.2f}** "
        f"({'fort ✅' if idea.overall_score >= 0.8 else 'modéré ⚡' if idea.overall_score >= 0.65 else 'faible ❌'}).\n\n"
        f"**Indicateurs au moment du scan** :\n{feat_lines}\n\n"
        f"{idea.explanation or ''}".strip()
    )
    return {"ok": True, "reply": reply, "action_request": None,
            "data": {"idea_id": idea.id}}


def analyze_portfolio(user, conversation, entities):
    portfolio = _default_portfolio(user)
    if portfolio is None:
        return {"ok": False, "action_request": None, "data": {},
                "reply": "Aucun portefeuille actif. Crée-en un depuis la page Portfolio."}
    positions = portfolio.positions.filter(status__in=["OPEN", "PARTIALLY_CLOSED"])
    pos_lines = "\n".join(
        f"| {p.side} {p.symbol} | {p.quantity} | {p.average_entry_price} "
        f"| {p.current_price} | {p.unrealized_pnl:+.2f} |"
        for p in positions[:10]
    )
    reply = (
        f"## Portefeuille « {portfolio.name} »\n\n"
        f"| Équité | Solde | Cash dispo | PnL latent | PnL réalisé | Drawdown |\n|---|---|---|---|---|---|\n"
        f"| **{portfolio.equity:.2f}** | {portfolio.current_balance:.2f} "
        f"| {portfolio.available_cash:.2f} | {portfolio.unrealized_pnl:+.2f} "
        f"| {portfolio.realized_pnl:+.2f} | {portfolio.current_drawdown_percent:.1f}% |\n"
        + (f"\n### Positions ouvertes ({positions.count()})\n"
           f"| Position | Qté | Entrée | Actuel | PnL |\n|---|---|---|---|---|\n{pos_lines}"
           if pos_lines else "\nAucune position ouverte.")
    )
    return {"ok": True, "reply": reply, "action_request": None,
            "data": {"portfolio_id": portfolio.id}}


def analyze_risk(user, conversation, entities):
    from risk.services import RiskGuardService, RiskStateService

    portfolio = _default_portfolio(user)
    if portfolio is None:
        return {"ok": False, "action_request": None, "data": {},
                "reply": "Aucun portefeuille actif."}
    daily = RiskStateService.refresh_daily_state(portfolio)
    weekly = RiskStateService.refresh_weekly_state(portfolio)
    monthly = RiskStateService.refresh_monthly_state(portfolio)
    ks = RiskGuardService.has_active_kill_switch(portfolio)
    profile = RiskGuardService.get_default_profile(portfolio)
    reply = (
        f"## État du risque — {portfolio.name}\n\n"
        f"| Fenêtre | Perte | Limite |\n|---|---|---|\n"
        f"| Jour | {daily.total_loss_percent:.2f}% | {profile.max_daily_loss}% |\n"
        f"| Semaine | {weekly.total_loss_percent:.2f}% | {profile.max_weekly_loss}% |\n"
        f"| Mois | {monthly.total_loss_percent:.2f}% | {profile.max_monthly_loss}% |\n\n"
        f"Drawdown courant : **{portfolio.current_drawdown_percent:.1f}%** "
        f"(max autorisé {profile.max_drawdown}%). "
        f"Kill switch : {'🛑 **ACTIF**' if ks else '✅ inactif'}."
    )
    return {"ok": True, "reply": reply, "action_request": None,
            "data": {"kill_switch": ks}}


# ─────────────────────────────────────────────────────────────────────────────
# Tools ACTION (→ AssistantActionRequest, jamais d'exécution directe)
# ─────────────────────────────────────────────────────────────────────────────

def _request_reply(request, intro: str) -> str:
    live = request.mode == "LIVE"
    badge = "🔴 **LIVE — argent réel**" if live else "🟡 PAPER (simulation)"
    risk = request.risk_summary or {}
    risk_line = ""
    if risk.get("decision"):
        risk_line = (
            f"\n> Risk Engine : **{risk['decision']}**"
            + (f" — {risk.get('blocking_reason')}" if risk.get("blocking_reason") else "")
        )
    confirm_hint = (
        "Confirme **deux fois** (mode LIVE) pour exécuter, ou réponds « non » pour annuler."
        if live else
        "Réponds « **oui je confirme** » pour exécuter, ou « non » pour annuler."
    )
    return f"{intro}\n\n{request.summary}\n\nMode : {badge}{risk_line}\n\n{confirm_hint}"


def prepare_trade_execution(user, conversation, entities):
    idea = _resolve_idea(user, entities, conversation)
    if idea is None:
        return {"ok": False, "action_request": None, "data": {},
                "reply": "Aucune idée exploitable trouvée. Demande-moi d'abord "
                         "« trouve des opportunités », ou précise #ID / symbole."}

    portfolio = _default_portfolio(user)
    if portfolio is None:
        return {"ok": False, "action_request": None, "data": {},
                "reply": "Aucun portefeuille actif — impossible de préparer un trade."}
    broker = portfolio.broker_account
    mode = entities.get("mode") or getattr(broker, "mode", "PAPER")

    amount = entities.get("amount")
    if not amount:
        return {"ok": False, "action_request": None, "data": {"idea_id": idea.id},
                "reply": f"Quel montant veux-tu engager sur {idea.direction} "
                         f"{idea.symbol} (#{idea.id}) ? Ex. : « exécute #{idea.id} avec 25 USDT »."}

    guards = AssistantRiskValidationService.validate_trade_preparation(
        user=user, portfolio=portfolio, broker_account=broker,
        amount=amount, mode=mode,
    )
    if not guards.ok:
        return {"ok": False, "action_request": None,
                "data": {"block_code": guards["code"]},
                "reply": f"⛔ Action bloquée : {guards['message']}"}

    risk = AssistantRiskValidationService.risk_preview(
        portfolio=portfolio, idea=idea, stake_amount=amount,
    )
    if risk.get("decision") in ("BLOCK", "REJECT"):
        return {"ok": False, "action_request": None, "data": {"risk": risk},
                "reply": f"⛔ Le Risk Engine refuse cette exécution : "
                         f"{risk.get('blocking_reason') or risk.get('block_code')}. "
                         f"Je ne préparerai pas cet ordre."}

    summary = (
        f"| Champ | Valeur |\n|---|---|\n"
        f"| Actif | **{idea.symbol}** |\n"
        f"| Direction | **{idea.direction}** |\n"
        f"| Montant | **{Decimal(str(amount)):.2f} USDT** |\n"
        f"| Entrée estimée | {idea.entry_price} |\n"
        f"| Stop loss | {idea.stop_loss or '—'} |\n"
        f"| Take profit | {idea.take_profit or '—'} |\n"
        f"| Risque estimé | {risk.get('expected_loss', '—')} $ |\n"
        f"| Gain visé | {risk.get('expected_gain', '—')} $ |\n"
        f"| R/R | {risk.get('risk_reward_ratio', '—')} |\n"
        f"| Portefeuille | {portfolio.name} |\n"
        f"| Broker | {broker.name} ({broker.broker}) |"
    )
    request = AssistantActionService.create_request(
        user=user, conversation=conversation,
        intent="PREPARE_TRADE", action_type="EXECUTE_TRADE_IDEA",
        target_type="TradeIdea", target_id=idea.id,
        mode=mode, summary=summary, risk_summary=risk,
        payload={"portfolio_id": portfolio.id, "broker_account_id": broker.id,
                 "stake_amount": str(amount)},
    )
    return {
        "ok": True,
        "reply": _request_reply(request, "J'ai préparé l'ordre suivant — le Risk Engine "
                                         f"répond **{risk.get('decision', '—')}** :"),
        "action_request": AssistantActionService.serialize(request),
        "data": {"idea_id": idea.id},
    }


def _simple_action(user, conversation, *, intent, action_type, target_type="",
                   target_id=None, mode="PAPER", summary, payload=None):
    request = AssistantActionService.create_request(
        user=user, conversation=conversation, intent=intent,
        action_type=action_type, target_type=target_type, target_id=target_id,
        mode=mode, summary=summary, payload=payload or {},
    )
    return {
        "ok": True,
        "reply": _request_reply(request, "Voici ce que je vais faire :"),
        "action_request": AssistantActionService.serialize(request),
        "data": {},
    }


def cancel_order(user, conversation, entities):
    from execution.models import Order

    qs = Order.objects.filter(
        user=user, status__in=["PENDING_SUBMIT", "SUBMITTED", "PARTIALLY_FILLED"],
    ).order_by("-created_at")
    if entities.get("ref_id"):
        qs = qs.filter(pk=entities["ref_id"])
    elif entities.get("symbol"):
        qs = qs.filter(symbol__iexact=entities["symbol"])
    order = qs.first()
    if order is None:
        return {"ok": False, "action_request": None, "data": {},
                "reply": "Aucun ordre ouvert annulable trouvé."}
    return _simple_action(
        user, conversation, intent="CANCEL_ORDER", action_type="CANCEL_ORDER",
        target_type="Order", target_id=order.id, mode=order.mode,
        summary=(f"Annuler l'ordre **#{order.id}** : {order.side} {order.symbol}, "
                 f"qté {order.approved_quantity}, statut actuel {order.status}. "
                 f"Le cash réservé sera libéré."),
    )


def _resolve_position(user, entities):
    from portfolio.models import Position

    qs = Position.objects.filter(
        portfolio__user=user, status__in=["OPEN", "PARTIALLY_CLOSED"],
    ).select_related("portfolio")
    if entities.get("ref_id"):
        return qs.filter(pk=entities["ref_id"]).first()
    if entities.get("symbol"):
        return qs.filter(symbol__iexact=entities["symbol"]).order_by("-opened_at").first()
    return None


def close_position(user, conversation, entities):
    position = _resolve_position(user, entities)
    if position is None:
        return {"ok": False, "action_request": None, "data": {},
                "reply": "Quelle position ? Précise le symbole (ex. « ferme ma position BTC »)."}
    pnl = Decimal(str(position.unrealized_pnl or 0))
    return _simple_action(
        user, conversation, intent="CLOSE_POSITION", action_type="CLOSE_POSITION",
        target_type="Position", target_id=position.id,
        mode=getattr(position.broker_account, "mode", "PAPER"),
        summary=(f"Fermer **{position.side} {position.symbol}** "
                 f"(qté {position.quantity}, entrée {position.average_entry_price}). "
                 f"Impact estimé : PnL latent **{pnl:+.2f} $** sera réalisé "
                 f"(hors frais et slippage)."),
    )


def reduce_position(user, conversation, entities):
    position = _resolve_position(user, entities)
    if position is None:
        return {"ok": False, "action_request": None, "data": {},
                "reply": "Quelle position réduire ? Ex. « réduis ma position ETH de 50% »."}
    percent = int(entities.get("percent") or 50)
    pnl_part = Decimal(str(position.unrealized_pnl or 0)) * Decimal(percent) / 100
    return _simple_action(
        user, conversation, intent="REDUCE_POSITION", action_type="REDUCE_POSITION",
        target_type="Position", target_id=position.id,
        mode=getattr(position.broker_account, "mode", "PAPER"),
        summary=(f"Réduire **{position.side} {position.symbol}** de **{percent}%** "
                 f"(≈ {Decimal(str(position.quantity)) * percent / 100}). "
                 f"PnL réalisé estimé sur la part fermée : **{pnl_part:+.2f} $**."),
        payload={"percent": percent},
    )


def sync_portfolio(user, conversation, entities):
    portfolio = _default_portfolio(user)
    if portfolio is None:
        return {"ok": False, "action_request": None, "data": {},
                "reply": "Aucun portefeuille actif."}
    return _simple_action(
        user, conversation, intent="SYNC_PORTFOLIO", action_type="SYNC_PORTFOLIO",
        target_type="Portfolio", target_id=portfolio.id,
        summary=f"Synchroniser « {portfolio.name} » avec le broker "
                f"(réconciliation des ordres + recalcul des soldes).",
        payload={"portfolio_id": portfolio.id},
    )


def test_broker_connection(user, conversation, entities):
    from brokers.models import BrokerAccount

    broker = (BrokerAccount.objects.filter(user=user, is_active=True)
              .order_by("-is_default").first())
    if broker is None:
        return {"ok": False, "action_request": None, "data": {},
                "reply": "Aucun compte broker configuré."}
    return _simple_action(
        user, conversation, intent="TEST_BROKER", action_type="TEST_BROKER",
        target_type="BrokerAccount", target_id=broker.id,
        summary=f"Tester la connexion au broker **{broker.name}** ({broker.broker}, "
                f"mode {broker.mode}).",
    )


def activate_kill_switch(user, conversation, entities):
    portfolio = _default_portfolio(user)
    if portfolio is None:
        return {"ok": False, "action_request": None, "data": {},
                "reply": "Aucun portefeuille actif."}
    return _simple_action(
        user, conversation, intent="ACTIVATE_KILL_SWITCH",
        action_type="ACTIVATE_KILL_SWITCH",
        target_type="Portfolio", target_id=portfolio.id,
        mode=getattr(portfolio.broker_account, "mode", "PAPER"),
        summary=(f"🛑 Activer le **kill switch** sur « {portfolio.name} » : "
                 f"toutes les nouvelles entrées seront bloquées jusqu'à levée manuelle. "
                 f"Les positions ouvertes ne sont PAS fermées automatiquement."),
        payload={"portfolio_id": portfolio.id},
    )


def disable_auto_trading(user, conversation, entities):
    return _simple_action(
        user, conversation, intent="DISABLE_AUTO_TRADING",
        action_type="DISABLE_AUTO_TRADING",
        summary=("Désactiver l'**auto-trading** : toutes tes trade ideas repassent "
                 "en validation manuelle — plus aucune exécution automatique."),
    )


# Cycle de vie idée (sensible → confirmation, mais sans double LIVE)
def approve_trade_idea(user, conversation, entities):
    idea = _resolve_idea(user, entities, conversation)
    if idea is None:
        return {"ok": False, "action_request": None, "data": {},
                "reply": "Quelle idée approuver ? Donne-moi son #ID ou son symbole."}
    return _simple_action(
        user, conversation, intent="APPROVE_TRADE_IDEA", action_type="APPROVE_TRADE_IDEA",
        target_type="TradeIdea", target_id=idea.id,
        summary=f"Approuver l'idée **#{idea.id} {idea.direction} {idea.symbol}** "
                f"(score {idea.overall_score:.2f}).",
    )


def reject_trade_idea(user, conversation, entities):
    idea = _resolve_idea(user, entities, conversation)
    if idea is None:
        return {"ok": False, "action_request": None, "data": {},
                "reply": "Quelle idée rejeter ? Donne-moi son #ID ou son symbole."}
    return _simple_action(
        user, conversation, intent="REJECT_TRADE_IDEA", action_type="REJECT_TRADE_IDEA",
        target_type="TradeIdea", target_id=idea.id,
        summary=f"Rejeter l'idée **#{idea.id} {idea.direction} {idea.symbol}**.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Registre
# ─────────────────────────────────────────────────────────────────────────────

class AssistantToolRegistry:
    TOOLS = {
        "find_trade_ideas": find_trade_ideas,
        "explain_trade_idea": explain_trade_idea,
        "prepare_trade_execution": prepare_trade_execution,
        "approve_trade_idea": approve_trade_idea,
        "reject_trade_idea": reject_trade_idea,
        "cancel_order": cancel_order,
        "close_position": close_position,
        "reduce_position": reduce_position,
        "sync_portfolio": sync_portfolio,
        "analyze_portfolio": analyze_portfolio,
        "analyze_risk": analyze_risk,
        "test_broker_connection": test_broker_connection,
        "activate_kill_switch": activate_kill_switch,
        "disable_auto_trading": disable_auto_trading,
    }

    # Intent → tool (les intents CONFIRM/CANCEL sont gérés par la couche
    # confirmation, GENERAL_CHAT et EXPLAIN long par le LLM)
    INTENT_TOOLS = {
        "ASK_MARKET_OPPORTUNITY": "find_trade_ideas",
        "EXPLAIN_TRADE_IDEA": "explain_trade_idea",
        "PREPARE_TRADE": "prepare_trade_execution",
        "APPROVE_TRADE_IDEA": "approve_trade_idea",
        "REJECT_TRADE_IDEA": "reject_trade_idea",
        "CANCEL_ORDER": "cancel_order",
        "CLOSE_POSITION": "close_position",
        "REDUCE_POSITION": "reduce_position",
        "SYNC_PORTFOLIO": "sync_portfolio",
        "TEST_BROKER": "test_broker_connection",
        "ACTIVATE_KILL_SWITCH": "activate_kill_switch",
        "DISABLE_AUTO_TRADING": "disable_auto_trading",
        "PORTFOLIO_ANALYSIS": "analyze_portfolio",
        "RISK_ANALYSIS": "analyze_risk",
    }

    @classmethod
    def run(cls, tool_name: str, user, conversation, entities: dict) -> dict:
        tool = cls.TOOLS.get(tool_name)
        if tool is None:
            return {"ok": False, "reply": f"Outil inconnu : {tool_name}",
                    "action_request": None, "data": {}}
        try:
            return tool(user, conversation, entities or {})
        except Exception as exc:
            log.exception("tools.run_failed tool=%s", tool_name)
            return {"ok": False, "action_request": None, "data": {},
                    "reply": f"L'outil a rencontré une erreur : {str(exc)[:200]}"}

    @classmethod
    def for_intent(cls, intent: str) -> str | None:
        return cls.INTENT_TOOLS.get(intent)

    @classmethod
    def describe(cls) -> list[dict]:
        return [
            {"name": name, "doc": (fn.__doc__ or "").strip().split("\n")[0]}
            for name, fn in cls.TOOLS.items()
        ]
