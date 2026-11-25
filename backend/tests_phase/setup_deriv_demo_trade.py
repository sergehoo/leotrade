"""
tests_phase/setup_deriv_demo_trade.py
=======================================

Script de SETUP + TRADE DE TEST sur compte Deriv demo.

Ce script fait tout en une seule passe :
  1. Crée ou récupère le BrokerAccount Deriv demo
  2. Stocke le token Deriv de façon chiffrée
  3. Crée ou récupère un Portfolio lié
  4. Crédite le portfolio du solde de départ (pour les tests)
  5. Teste la connexion Deriv (balance, portfolio)
  6. Passe un contrat de test (CALL sur R_100, mise = 1 USD)
  7. Affiche le résultat complet

USAGE :
    Ouvre un terminal dans le dossier leoTrade, active le venv, puis :

        source venv/bin/activate          # (Linux/Mac)
        # ou : venv\Scripts\activate      # (Windows)

        python manage.py shell

    Dans le shell Django, tape :

        exec(open('tests_phase/setup_deriv_demo_trade.py').read())

    Ou configure les variables ci-dessous et lance directement :

        LEOTRADE_DERIV_TOKEN=TON_TOKEN python manage.py shell < tests_phase/setup_deriv_demo_trade.py

VARIABLES À CONFIGURER :
    Modifie les 3 lignes dans la section "Configuration" ci-dessous.
"""

import os
import sys
from decimal import Decimal
from django.contrib.auth import get_user_model

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION — à modifier avant de lancer
# ═══════════════════════════════════════════════════════════════

# Ton token API Deriv DEMO
# → https://app.deriv.com/account/api-token
# Crée un token avec les scopes : Read, Trade, Payments, Admin
DERIV_TOKEN = os.environ.get("LEOTRADE_DERIV_TOKEN", "TON_TOKEN_ICI")

# L'App ID Deriv de LeoTrade (ou celui de ta propre app sur https://app.deriv.com/account/api-token)
# L'app ID par défaut pour dev/demo : 36544 (DerivGo) ou enregistre le tien
DERIV_APP_ID = os.environ.get("LEOTRADE_DERIV_APP_ID", "36544")

# L'email de l'utilisateur LeoTrade que tu veux utiliser
USER_EMAIL = os.environ.get("LEOTRADE_USER_EMAIL", "sergehoo@gmail.com")

# Symbole Deriv à trader (compte demo synthétiques uniquement)
SYMBOL = "R_100"          # Volatility 100 Index — disponible 24h/24 en demo
SIDE = "BUY"              # BUY = CALL
STAKE_AMOUNT = Decimal("1.00")  # Mise en USD (minimum Deriv = 0.35 USD sur demo)
DURATION = 5              # Durée
DURATION_UNIT = "m"       # m = minutes, s = secondes, h = heures, d = jours

# ═══════════════════════════════════════════════════════════════
# SCRIPT
# ═══════════════════════════════════════════════════════════════

print("\n" + "═" * 65)
print("  LEOTRADE — SETUP + TRADE DEMO DERIV")
print("═" * 65)

if DERIV_TOKEN in ("TON_TOKEN_ICI", "", None):
    print("\n❌ ERREUR : tu n'as pas configuré DERIV_TOKEN.")
    print("   Modifie la variable DERIV_TOKEN en haut du script,")
    print("   ou lance avec : LEOTRADE_DERIV_TOKEN=xxxx python manage.py shell < ...")
    sys.exit(1)

User = get_user_model()

# ─── 1. Récupérer l'utilisateur ───────────────────────────────
print(f"\n[1/7] Recherche utilisateur : {USER_EMAIL}")
try:
    user = User.objects.get(email=USER_EMAIL)
    print(f"      ✅ Utilisateur trouvé : {user.username} (id={user.id})")
except User.DoesNotExist:
    print(f"      ⚠️  Utilisateur introuvable — création d'un compte temporaire")
    user = User.objects.create_user(
        username="deriv_demo_user",
        email=USER_EMAIL,
        password="ChangeMe123!",
    )
    print(f"      ✅ Utilisateur créé : {user.username} (id={user.id})")

# ─── 2. Créer/récupérer le BrokerAccount Deriv demo ───────────
print(f"\n[2/7] Création du BrokerAccount Deriv DEMO")
from brokers.models import BrokerAccount

broker, created = BrokerAccount.objects.get_or_create(
    user=user,
    broker="DERIV",
    mode="DEMO",
    defaults={
        "name": "Deriv Demo",
        "is_active": True,
        "deriv_app_id": DERIV_APP_ID,
        "deriv_currency": "USD",
        "deriv_account_type": "demo",
    },
)

if not created:
    # Mettre à jour l'app_id si nécessaire
    if broker.deriv_app_id != DERIV_APP_ID:
        broker.deriv_app_id = DERIV_APP_ID
        broker.save(update_fields=["deriv_app_id", "updated_at"])
    print(f"      ✅ BrokerAccount existant récupéré (id={broker.id})")
else:
    print(f"      ✅ BrokerAccount créé (id={broker.id})")

# ─── 3. Stocker le token Deriv (chiffré) ─────────────────────
print(f"\n[3/7] Stockage du token Deriv (chiffré en base)")
broker.set_secret("DERIV_TOKEN", DERIV_TOKEN)
# Vérification que le round-trip fonctionne
recovered = broker.deriv_token
if recovered == DERIV_TOKEN:
    print(f"      ✅ Token stocké et récupéré avec succès (len={len(DERIV_TOKEN)})")
else:
    print(f"      ❌ Problème de chiffrement — token récupéré différent de l'original")
    sys.exit(1)

# ─── 4. Créer/récupérer le Portfolio ─────────────────────────
print(f"\n[4/7] Création du Portfolio")
from portfolio.models import Portfolio, CashLedgerEntry

portfolio, p_created = Portfolio.objects.get_or_create(
    user=user,
    broker_account=broker,
    defaults={
        "name": "Portfolio Deriv Demo",
        "base_currency": "USD",
        "starting_balance": Decimal("0.00"),
        "current_balance": Decimal("0.00"),
        "available_cash": Decimal("0.00"),
        "is_default": True,
        "is_active": True,
    },
)

if not p_created:
    print(f"      ✅ Portfolio existant récupéré (id={portfolio.id})")
else:
    print(f"      ✅ Portfolio créé (id={portfolio.id})")

# Recalcule le cash disponible depuis le ledger
from portfolio.services import PortfolioService, PortfolioAccountingService
portfolio = PortfolioService.recompute_cash_state(portfolio)
print(f"      💰 Cash disponible : {portfolio.available_cash} USD")

# Si le portfolio est vide, on injecte un solde de test
if portfolio.available_cash < STAKE_AMOUNT:
    seed_amount = max(Decimal("100.00"), STAKE_AMOUNT * 10)
    print(f"\n      ℹ️  Portfolio insuffisant → injection de {seed_amount} USD (test uniquement)")
    PortfolioAccountingService.add_ledger_entry(
        portfolio=portfolio,
        entry_type="DEPOSIT",
        amount=seed_amount,
        currency="USD",
        reference_type="DEMO_SEED",
        reference_id="initial",
        description="Solde de départ pour test Deriv demo",
        metadata={"source": "setup_script"},
    )
    portfolio = PortfolioService.recompute_cash_state(portfolio)
    print(f"      ✅ Nouveau solde : {portfolio.available_cash} USD")

# ─── 5. Tester la connexion Deriv ────────────────────────────
print(f"\n[5/7] Test de connexion Deriv")
from brokers.services.deriv import DerivClient, DerivClientError

client = None
try:
    client = DerivClient(token=DERIV_TOKEN, app_id=str(DERIV_APP_ID))

    print("      → Lecture des comptes options...")
    accounts_resp = client.list_options_accounts()
    accounts = accounts_resp.get("data", []) or []
    if not accounts:
        print("      ❌ Aucun compte Deriv retourné — vérifie ton token et app_id")
        sys.exit(1)

    selected_account = None
    for acc in accounts:
        if str(acc.get("account_type", "")).lower() == "demo":
            selected_account = acc
            break
    if not selected_account:
        selected_account = accounts[0]

    account_id = selected_account.get("account_id") or selected_account.get("id")
    print(f"      ✅ Compte Deriv : {account_id} (type: {selected_account.get('account_type', '?')})")

    print("      → Connexion WebSocket OTP...")
    ws_url = client.get_otp_ws_url(str(account_id))
    client.connect_with_otp_url(ws_url)
    print("      ✅ WebSocket connecté")

    print("      → Balance...")
    bal_resp = client.balance_ws()
    bal_data = bal_resp.get("balance") or {}
    balance_amount = bal_data.get("balance", "?")
    balance_currency = bal_data.get("currency", "?")
    print(f"      ✅ Balance Deriv : {balance_amount} {balance_currency}")

    print("      → Portfolio ouvert...")
    pf_resp = client.portfolio_ws()
    contracts = (pf_resp.get("portfolio") or {}).get("contracts") or []
    print(f"      ✅ Contrats ouverts sur Deriv : {len(contracts)}")

except DerivClientError as e:
    print(f"      ❌ Erreur Deriv : {e}")
    print("\n      ⚠️  Conseils de dépannage :")
    print("         • Vérifie ton token sur https://app.deriv.com/account/api-token")
    print("         • Le token doit avoir les scopes : Read, Trade, Payments, Admin")
    print("         • Pour un compte demo, assure-toi que l'app_id est valide")
    print("         • App ID par défaut : 36544 (ou enregistre le tien sur Deriv)")
    if client:
        client.close()
    sys.exit(1)
except Exception as e:
    print(f"      ❌ Erreur inattendue : {e}")
    if client:
        client.close()
    sys.exit(1)
finally:
    if client:
        client.close()

# ─── 6. Exécuter un trade de test ────────────────────────────
print(f"\n[6/7] Exécution du trade de test")
print(f"      Symbole : {SYMBOL}")
print(f"      Sens    : {SIDE} (CALL)")
print(f"      Mise    : {STAKE_AMOUNT} USD")
print(f"      Durée   : {DURATION}{DURATION_UNIT}")

from django.utils.text import slugify
from market.models import Asset, Timeframe
from strategies.models import Strategy, Signal

asset, _ = Asset.objects.get_or_create(
    symbol=SYMBOL,
    defaults={
        "asset_class": "INDEX",
        "exchange": "DERIV",
        "is_active": True,
    },
)

timeframe, _ = Timeframe.objects.get_or_create(
    code="deriv",
    defaults={"label": "Deriv Contract", "minutes": 1},
)

strategy, _ = Strategy.objects.get_or_create(
    slug=slugify(f"deriv-{SYMBOL}-{SIDE}-{DURATION}{DURATION_UNIT}"),
    defaults={
        "name": f"Deriv {SYMBOL} {SIDE}",
        "strategy_type": "RULE",
        "asset": asset,
        "timeframe": timeframe,
        "status": "PAPER",
        "is_active": True,
        "is_autonomous": False,
        "allow_live_execution": False,
        "min_confidence_threshold": 0.1,
        "parameters": {
            "deriv_duration": DURATION,
            "deriv_duration_unit": DURATION_UNIT,
        },
    },
)

from django.utils import timezone
signal = Signal.objects.create(
    strategy=strategy,
    candle_time=timezone.now(),
    side=SIDE,
    confidence=0.99,
    price=Decimal("0"),
    status="APPROVED",
    reason=f"Trade de test — {SYMBOL} {SIDE} {DURATION}{DURATION_UNIT}",
)

from trading.services.execution.deriv_executor import DerivExecutor, DerivExecutorError

executor = DerivExecutor(broker, portfolio)

try:
    result = executor.execute_signal(signal, STAKE_AMOUNT)

    order = result["order"]
    contract = result["contract"]
    position = result["position"]

    print(f"\n      ✅ TRADE EXÉCUTÉ AVEC SUCCÈS !")
    print(f"\n      ┌─ Résumé du trade ─────────────────────────────")
    print(f"      │  Order ID       : {order.id}")
    print(f"      │  Contract ID    : {contract.contract_id}")
    print(f"      │  Transaction ID : {contract.transaction_id or 'N/A'}")
    print(f"      │  Symbole        : {contract.symbol}")
    print(f"      │  Type           : {contract.contract_type}")
    print(f"      │  Mise           : {contract.buy_price} {contract.currency}")
    print(f"      │  Durée          : {contract.duration}{contract.duration_unit}")
    print(f"      │  Statut         : {contract.status}")
    print(f"      │  Expire à       : {contract.expires_at}")
    print(f"      │  Position ID    : {position.id}")
    print(f"      └────────────────────────────────────────────────")

except DerivExecutorError as e:
    print(f"\n      ❌ Erreur d'exécution : {e}")
    sys.exit(1)

# ─── 7. État post-trade ───────────────────────────────────────
print(f"\n[7/7] État post-trade")
portfolio.refresh_from_db()
portfolio = PortfolioService.recompute_cash_state(portfolio)

from execution.models import Order
from portfolio.models import Position

orders_count = Order.objects.filter(portfolio=portfolio).count()
open_positions = Position.objects.filter(portfolio=portfolio, status="OPEN").count()

print(f"      💰 Cash disponible   : {portfolio.available_cash} USD")
print(f"      📊 Ordres totaux     : {orders_count}")
print(f"      📈 Positions ouvertes: {open_positions}")

print(f"\n" + "═" * 65)
print(f"  ✅ SETUP ET TRADE TERMINÉS")
print(f"")
print(f"  Prochaines étapes :")
print(f"  • Voir l'ordre dans l'admin Django : /admin/execution/order/")
print(f"  • Voir le contrat : /admin/trading/derivcontract/")
print(f"  • Surveiller la clôture via la tâche Celery :")
print(f"      python manage.py test_deriv_connection --broker-id={broker.id}")
print(f"  • IDs utiles pour d'autres tests :")
print(f"      BROKER_ID    = {broker.id}")
print(f"      PORTFOLIO_ID = {portfolio.id}")
print(f"      ORDER_ID     = {order.id}")
print(f"      CONTRACT_ID  = {contract.contract_id}")
print("═" * 65 + "\n")
