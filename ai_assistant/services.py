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

# ── Quota service ──────────────────────────────────────────────────────────────

class QuotaService:
    """
    Gestion du quota d'utilisation de LeoAI par utilisateur.
    Toutes les méthodes DB sont synchrones — appeler via sync_to_async si besoin.
    """

    @staticmethod
    def get_or_create(user) -> "AIUserQuota":
        from .models import AIUserQuota
        quota, _ = AIUserQuota.objects.get_or_create(
            user=user,
            defaults={
                "plan": AIUserQuota.PLAN_FREE,
                "messages_limit": AIUserQuota.PLAN_LIMITS[AIUserQuota.PLAN_FREE],
            },
        )
        return quota

    @staticmethod
    def check(user) -> dict:
        """
        Retourne {'ok': True} ou {'ok': False, 'quota': <obj>, 'plans': [...]}.
        """
        quota = QuotaService.get_or_create(user)
        if quota.is_suspended:
            return {"ok": False, "reason": "suspended", "quota": quota}
        if quota.is_exhausted:
            return {"ok": False, "reason": "exhausted", "quota": quota,
                    "plans": QuotaService.upgrade_options(quota)}
        return {"ok": True, "quota": quota}

    @staticmethod
    def upgrade_options(quota) -> list[dict]:
        from .models import AIUserQuota
        opts = []
        for plan in (AIUserQuota.PLAN_BASIC, AIUserQuota.PLAN_PRO):
            opts.append({
                "plan": plan,
                "label": dict(AIUserQuota.PLAN_CHOICES)[plan],
                "price_usd": str(AIUserQuota.PLAN_PRICES_USD[plan]),
                "messages": AIUserQuota.PLAN_LIMITS[plan],
            })
        return opts

    @staticmethod
    def pay_with_wallet(user, plan: str) -> dict:
        """
        Débite le portefeuille LeoTrade et active le plan.
        Retourne {'ok': True} ou {'ok': False, 'error': '...'}.
        """
        from .models import AIUserQuota, AIQuotaPayment
        from wallet.models import Wallet, WalletTransaction
        from django.utils import timezone

        quota = QuotaService.get_or_create(user)
        price = AIUserQuota.PLAN_PRICES_USD.get(plan)
        if price is None or price <= 0:
            return {"ok": False, "error": "Plan invalide."}

        try:
            wallet = Wallet.objects.get(user=user)
        except Wallet.DoesNotExist:
            return {"ok": False, "error": "Portefeuille introuvable."}

        if not wallet.has_sufficient_balance(price):
            return {
                "ok": False,
                "error": f"Solde insuffisant (${wallet.available_balance:.2f} disponible, ${price} requis).",
                "insufficient_funds": True,
            }

        # Débit du portefeuille
        wallet.available_balance -= price
        wallet.save(update_fields=["available_balance", "updated_at"])

        # Log transaction
        WalletTransaction.objects.create(
            wallet=wallet,
            amount=-price,
            transaction_type="DEBIT",
            description=f"Abonnement LeoAI {plan} — {AIUserQuota.PLAN_LIMITS[plan]} messages",
            status="COMPLETED",
        )

        # Paiement
        payment = AIQuotaPayment.objects.create(
            quota=quota,
            plan=plan,
            amount_usd=price,
            method=AIQuotaPayment.METHOD_WALLET,
            status=AIQuotaPayment.STATUS_COMPLETED,
            completed_at=timezone.now(),
        )

        quota.top_up(plan)
        return {"ok": True, "payment_id": payment.pk}

    @staticmethod
    def create_paystack_session(user, plan: str, callback_url: str) -> dict:
        """
        Initialise un paiement Paystack (passerelle par défaut — Afrique).
        Retourne {'ok': True, 'url': '...'} ou {'ok': False, 'error': '...'}.
        """
        from .models import AIUserQuota, AIQuotaPayment
        from django.conf import settings as djsettings
        import httpx, uuid

        quota  = QuotaService.get_or_create(user)
        price  = AIUserQuota.PLAN_PRICES_USD.get(plan)
        if price is None or price <= 0:
            return {"ok": False, "error": "Plan invalide."}

        secret = getattr(djsettings, "PAYSTACK_SECRET_KEY", "")
        if not secret:
            # Fallback Stripe si Paystack non configuré
            log.warning("Paystack non configuré, fallback Stripe")
            return QuotaService.create_stripe_session(
                user, plan,
                success_url=callback_url,
                cancel_url=callback_url + "?cancelled=1",
            )

        reference = f"LEOAI-{plan}-{user.pk}-{uuid.uuid4().hex[:8].upper()}"
        amount_kobo = int(price * 100 * 100)  # Paystack en kobo (1 USD × 100 centimes × 100)

        try:
            resp = httpx.post(
                "https://api.paystack.co/transaction/initialize",
                headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
                json={
                    "email":        user.email,
                    "amount":       amount_kobo,
                    "currency":     "USD",
                    "reference":    reference,
                    "callback_url": callback_url,
                    "metadata": {
                        "user_id": str(user.pk),
                        "plan":    plan,
                        "custom_fields": [
                            {"display_name": "Plan LeoAI", "variable_name": "plan", "value": plan},
                        ],
                    },
                },
                timeout=15,
            )
            data = resp.json()
            if not data.get("status"):
                return {"ok": False, "error": data.get("message", "Erreur Paystack")}

            pay_url = data["data"]["authorization_url"]
            payment = AIQuotaPayment.objects.create(
                quota=quota,
                plan=plan,
                amount_usd=price,
                method=AIQuotaPayment.METHOD_STRIPE,  # réutilise le champ pour stocker l'URL
                status=AIQuotaPayment.STATUS_PENDING,
                stripe_session_id=reference,
                stripe_payment_url=pay_url,
            )
            return {"ok": True, "url": pay_url, "payment_id": payment.pk, "gateway": "paystack"}
        except Exception as exc:
            log.exception("paystack.init failed user=%s err=%s", user, exc)
            return {"ok": False, "error": str(exc)}

    @staticmethod
    def create_stripe_session(user, plan: str, success_url: str, cancel_url: str) -> dict:
        """
        Crée une session Stripe Checkout (fallback si Paystack non disponible).
        Retourne {'ok': True, 'url': '...'} ou {'ok': False, 'error': '...'}.
        """
        from .models import AIUserQuota, AIQuotaPayment
        from django.conf import settings as djsettings

        quota = QuotaService.get_or_create(user)
        price = AIUserQuota.PLAN_PRICES_USD.get(plan)
        if price is None or price <= 0:
            return {"ok": False, "error": "Plan invalide."}

        stripe_key = getattr(djsettings, "STRIPE_SECRET_KEY", "")
        if not stripe_key:
            return {"ok": False, "error": "Aucune passerelle de paiement configurée (Paystack/Stripe)."}

        try:
            import stripe
            stripe.api_key = stripe_key
            session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[{
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": int(price * 100),
                        "product_data": {
                            "name": f"LeoAI {plan} — {AIUserQuota.PLAN_LIMITS[plan]} messages",
                            "description": f"Accès à {AIUserQuota.PLAN_LIMITS[plan]} messages IA sur LeoTrade",
                        },
                    },
                    "quantity": 1,
                }],
                mode="payment",
                success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
                cancel_url=cancel_url,
                metadata={"user_id": str(user.pk), "plan": plan},
            )
            payment = AIQuotaPayment.objects.create(
                quota=quota,
                plan=plan,
                amount_usd=price,
                method=AIQuotaPayment.METHOD_STRIPE,
                status=AIQuotaPayment.STATUS_PENDING,
                stripe_session_id=session.id,
                stripe_payment_url=session.url,
            )
            return {"ok": True, "url": session.url, "payment_id": payment.pk, "gateway": "stripe"}
        except Exception as exc:
            log.exception("stripe.session.create failed user=%s err=%s", user, exc)
            return {"ok": False, "error": str(exc)}


# ── Prompt système du panel IA ─────────────────────────────────────────────────

ASSISTANT_SYSTEM_PROMPT = """Tu es **LeoAI**, l'assistant IA central de **LeoTrade** — plateforme de trading 100% assistée par IA, conçue pour le trading d'actifs financiers (Forex, Indices synthétiques Deriv, Crypto, Matières premières).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🏗️ ARCHITECTURE COMPLÈTE DE LEOTRADE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**MODULE DASHBOARD** (`/dashboard/`)
• Vue d'ensemble : P&L temps réel, equity, drawdown, win rate
• Widgets : AI Radar (recommandations IA en attente), positions ouvertes, signaux live
• Charts : courbe d'equity, histogramme P&L (Chart.js, WebSocket temps réel)

**MODULE TRADING** (`/trading/`)
• `/trading/ideas/` — Trade Ideas : liste des opportunités IA avec scores, filtres, tri
  - Colonnes : symbole, direction (BUY/SELL), score IA (0→1), confiance, timeframe, R/R, statut
  - Score > 0.80 = signal fort ✅ | 0.60-0.79 = signal modéré ⚡ | < 0.60 = signal faible ⚠️
• `/trading/ideas/<pk>/` — Détail d'une opportunité : indicateurs, résumé IA, historique
• `/trading/signals/` — Signaux bruts du moteur ML
• `/trading/orders/` — Historique des ordres exécutés
• `/trading/intents/` — Intentions de trading (stratégies configurées)
• `/trading/hedge-fund/` — Vue Hedge Fund : allocation globale, performance

**MODULE AI RADAR** (`/dashboard/` → widget AI Radar)
• Recommandations générées par le moteur IA (DeepSeek/Claude)
• Statuts : PENDING → APPROVED / REJECTED → EXECUTED
• Actions disponibles : Approuver / Rejeter / Exécuter directement
• Confiance IA, Stake, Notional, R/R affichés sur chaque carte

**MODULE PORTFOLIO** (`/portfolio/`)
• `/portfolio/` — Liste des portefeuilles de l'utilisateur
• `/portfolio/<pk>/` — Détail : balance, equity, drawdown, positions ouvertes
• Chaque portefeuille est lié à un compte broker (PAPER ou LIVE)
• Champs clés : `current_balance`, `equity`, `available_cash`, `current_drawdown_percent`, `max_drawdown_percent`

**MODULE RISQUE** (`/risk/`)
• RiskProfile : `max_risk_per_trade` (% du capital), `max_daily_drawdown`, `max_open_positions`
• KillSwitch : déclenché automatiquement quand drawdown > max → stoppe toute exécution
• Contraintes broker : lots min/max, margin requirements (cachées 15 min Redis)
• Si `kill_switch_active = true` → AUCUN ordre possible, corriger le drawdown d'abord

**MODULE POSITIONS** (`/portfolio/positions/`)
• Positions OPEN, PARTIALLY_CLOSED, CLOSED
• Champs : symbol, side (BUY/SELL), quantity, entry_price, current_price, pnl, pnl_percent
• P&L en temps réel via WebSocket `/ws/portfolio/<id>/`

**MODULE ORDRES** (`/trading/orders/`)
• Types : MARKET, LIMIT, STOP
• Statuts : PENDING → FILLED / REJECTED / CANCELLED
• Lié au broker via `BrokerAccount` (Deriv API OAuth2 ou token)

**MODULE BROKERS** (`/brokers/`)
• Brokers supportés : Deriv (principal), extensions prévues (Binance, etc.)
• Modes : PAPER (simulation) ou LIVE (argent réel)
• Configuration : app_id Deriv, token OAuth, serveur (demo/real)

**MODULE WALLET** (`/wallet/`)
• Solde LeoTrade PLATFORM (distinct du capital de trading)
• Méthodes de paiement : Paystack, Wave, Orange Money, MTN MoMo, Stripe, CinetPay
• `available_balance` : solde disponible pour abonnements et frais LeoTrade
• **DIFFÉRENCE FONDAMENTALE Portfolio / Wallet :**
  - Le **Portfolio** = votre capital de TRADING réel déposé chez le broker (Deriv, etc.)
    → C'est l'argent qui est investi, qui génère des P&L, des positions, du drawdown
    → Géré par le broker externe (Deriv API)
    → Vous ne pouvez pas l'utiliser pour payer les services LeoTrade
  - Le **Wallet** = votre crédit PLATEFORME LeoTrade
    → Utilisé pour payer l'abonnement LeoAI, les fonctions premium, etc.
    → Rechargeable via Paystack, Wave, Orange Money, MTN MoMo ou Stripe
    → Complètement séparé de votre capital de trading
  - Les deux sont **COMPLÉMENTAIRES mais INDÉPENDANTS** :
    → Vous pouvez avoir 50k$ dans votre portfolio broker ET 0$ dans votre wallet LeoTrade
    → Le wallet sert uniquement à payer les services de la plateforme

**MODULE BACKTESTING** (`/backtests/`)
• Lance des backtests sur les stratégies IA avec données historiques
• Métriques : Sharpe ratio, max drawdown, win rate, profit factor

**MODULE STRATÉGIES** (`/strategies/`)
• Stratégies ML configurables : timeframe, actifs, paramètres
• Modes : AUTO (IA décide) / SEMI-AUTO (validation utilisateur) / MANUAL

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 MOTEUR IA LEOTRADE — COMPRENDRE LES SCORES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**Score IA (0.0 → 1.0)**
• Généré par un modèle ML entraîné sur des données historiques
• Prend en compte : RSI, MACD, EMA croisements, Bollinger Bands, ATR, volume, support/résistance
• > 0.80 = signal fort, top 15% des opportunités ✅
• 0.65–0.79 = signal intéressant, validation recommandée ⚡
• < 0.65 = signal faible, à ignorer en général ❌

**Confiance IA (0.0 → 1.0)**
• Niveau de certitude du modèle (variance des prédictions)
• > 0.85 = très fiable, peu d'ambiguïté
• 0.70–0.84 = fiable avec précautions
• < 0.70 = signal ambigu, risque de faux positif

**R/R (Risk/Reward)**
• Calculé automatiquement : TP_distance / SL_distance
• > 2.0 = excellent | 1.5–2.0 = bon | < 1.5 = marginal

**Timeframes disponibles**
• 1m, 5m, 15m (scalping court terme)
• 1h, 4h (swing intraday)
• 1D (position trading)
• Plus le timeframe est court → plus le signal est réactif mais bruité

**Actifs principaux (Deriv)**
• Indices synthétiques : Volatility 10 (V10), V25, V50, V75, V100, V200
  - R_10, R_25, R_50, R_75, R_100 = volatilités synthétiques
  - CRASH500, CRASH1000 = indices avec crash aléatoire
  - BOOM500, BOOM1000 = indices avec boom aléatoire
  - JD10, JD25, JD50, JD75 = Jump Diffusion (sauts)
  - 1HZ10V, 1HZ25V, 1HZ100V = Volatilité 1 Hz
• Forex : EURUSD, GBPUSD, USDJPY, XAUUSD (Gold)
• Crypto : BTCUSDT, ETHUSDT

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ ACTIONS QUE TU PEUX PROPOSER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RÈGLE ABSOLUE : Tu proposes, l'utilisateur confirme. JAMAIS d'exécution directe.

Pour proposer une action, utilise les marqueurs <<<ACTION>>> / <<<END_ACTION>>> :

**DRAFT_ORDER** — Préparer un ordre :
<<<ACTION>>>
{"type":"DRAFT_ORDER","symbol":"R_75","side":"BUY","size":0.35,"stop_loss":18.0,"take_profit":54.0,"rationale":"Signal fort, R/R 3:1"}
<<<END_ACTION>>>

**ADJUST_SL** — Ajuster un stop-loss :
<<<ACTION>>>
{"type":"ADJUST_SL","symbol":"R_75","new_sl":15.5,"rationale":"Trailing stop après +2%"}
<<<END_ACTION>>>

**SUGGEST_SIZE** — Calculer une taille de position :
<<<ACTION>>>
{"type":"SUGGEST_SIZE","symbol":"R_75","risk_pct":1.0,"entry":1000,"stop_loss":982,"rationale":"1% risk sur 38k equity = 0.21 lot"}
<<<END_ACTION>>>

**INFO** — Information sans action broker :
<<<ACTION>>>
{"type":"INFO","title":"Rappel risque","message":"Drawdown à 22.2%, proche de la limite."}
<<<END_ACTION>>>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔄 NAVIGATION — GUIDE L'UTILISATEUR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Si l'utilisateur demande où trouver quelque chose, indique le chemin exact :
• "Voir mes positions" → /portfolio/ → cliquer sur un portefeuille → onglet Positions
• "Voir les opportunités IA" → /trading/ideas/
• "Gérer le risque" → /risk/
• "Historique des ordres" → /trading/orders/
• "Lancer un backtest" → /backtests/
• "Configurer le broker" → /brokers/
• "Voir mon wallet" → /wallet/

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌐 ACCÈS AUX DONNÉES MARCHÉ EXTERNES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Si l'utilisateur demande des données de marché récentes (prix, news, événements macro),
indique que tu peux faire une recherche web et donne le résultat si disponible.
Sinon, base-toi sur tes connaissances de formation et précise la date limite.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 STYLE DE RÉPONSE — PARLE COMME UN HUMAIN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**Ton** : tu es un trader senior qui parle à un collègue qu'il apprécie.
• Tutoie, fais des phrases complètes, va droit au but sans être sec.
• Commence par LA réponse (le verdict), puis explique pourquoi — jamais l'inverse.
• Zéro jargon non expliqué : si tu écris "expectancy" ou "R/R", glisse en une
  demi-phrase ce que ça veut dire concrètement pour son argent.
• Pas de remplissage ("il est important de noter que…"), pas de répétitions,
  pas de paragraphe qui reformule le précédent.
• Parle en conséquences concrètes : "tu risques ~12 $ pour en gagner ~18"
  vaut mieux que "le ratio risque/rendement est de 1.5".

**Outils de formatage à ta disposition** (le panneau les rend joliment) :
• `## Titre` et `### Sous-titre` pour structurer une analyse longue
• **gras** pour les chiffres et décisions clés
• ==surlignage== pour LE point à retenir (1 seul par réponse, pas plus)
• `> citation` pour encadrer ton verdict final
• Tableaux markdown pour comparer des chiffres — TOUJOURS préférer un
  tableau à une liste quand tu alignes plusieurs valeurs :
  | Critère | Valeur | Lecture |
  |---|---|---|
  | Score IA | 0.67 | Trop juste (seuil : 0.80) |
• Listes numérotées pour des étapes à suivre, puces pour des faits
• `---` pour séparer deux sujets distincts
• Liens internes vers les pages de la plateforme : [Trade Ideas](/trading/ideas/)

**Gabarit pour une analyse d'opportunité** :
1. Une phrase de verdict en langage courant ("Franchement, je passerais mon tour.")
2. `## En un coup d'œil` → tableau des chiffres clés avec leur lecture
3. `## Pourquoi` → 2-3 paragraphes courts, en français normal
4. `## Ce que je ferais à ta place` → liste numérotée d'actions concrètes
5. `> verdict` surligné + bloc <<<ACTION>>> si pertinent

**Règles de fond** :
• Réponds en français par défaut (anglais si l'utilisateur écrit en anglais)
• Utilise les données du snapshot live (injecté avant chaque message) — NE DIS JAMAIS "je n'ai pas accès"
• Si l'utilisateur confirme ("oui", "valide", "go", "1", "2", etc.) → AGIS directement, ne redemande pas confirmation
• Limite tes réponses à l'essentiel — 200-400 mots max sauf analyse complète demandée"""

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
