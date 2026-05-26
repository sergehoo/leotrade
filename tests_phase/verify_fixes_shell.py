"""
tests_phase/verify_fixes_shell.py
===================================

Script de vérification RAPIDE à lancer dans le shell Django.

Usage :
    python manage.py shell < tests_phase/verify_fixes_shell.py

Ou en interactif :
    python manage.py shell
    >>> exec(open('tests_phase/verify_fixes_shell.py').read())

Ne nécessite pas pytest. Crée des objets réels en base de données de
développement et les nettoie à la fin (rollback via transaction.atomic).
"""

from decimal import Decimal
from django.db import transaction

print("\n" + "=" * 60)
print("  VÉRIFICATION DES CORRECTIFS — LeoTrade")
print("=" * 60 + "\n")

PASS = "  ✅ PASS"
FAIL = "  ❌ FAIL"
results = []


# ─────────────────────────────────────────────────────────────────
# CORRECTIF 1 — Pont Wallet → Portfolio
# ─────────────────────────────────────────────────────────────────
print("─── Correctif 1 : Pont Wallet → Portfolio ───")

try:
    with transaction.atomic():
        sp = transaction.savepoint()
        try:
            from django.contrib.auth import get_user_model
            from wallet.models import Wallet, WalletTransaction
            from portfolio.models import CashLedgerEntry, Portfolio
            from brokers.models import BrokerAccount

            User = get_user_model()
            user = User.objects.create_user(
                username="_verify_bridge_tmp", password="x",
            )
            wallet = Wallet.objects.get_or_create(user=user, defaults={"currency": "USD"})[0]
            broker = BrokerAccount.objects.create(
                user=user, broker="DERIV", name="test", mode="DEMO", is_active=True,
            )
            portfolio = Portfolio.objects.create(
                user=user, broker_account=broker, name="test",
                base_currency="USD", starting_balance=Decimal("0"),
                current_balance=Decimal("0"), available_cash=Decimal("0"),
                is_default=True, is_active=True,
            )

            # Créer transaction DEPOSIT SUCCEEDED
            tx = WalletTransaction.objects.create(
                wallet=wallet, tx_type="DEPOSIT",
                amount=Decimal("200.00"), currency="USD", status="SUCCEEDED",
            )
            tx.save()  # déclenche le signal

            entries = CashLedgerEntry.objects.filter(
                portfolio=portfolio,
                reference_type="WALLET_TRANSACTION",
                reference_id=str(tx.id),
            )

            if entries.count() == 1 and entries.first().amount == Decimal("200.00"):
                print(PASS + " — Dépôt 200 USD → 1 CashLedgerEntry créée")
                results.append(True)
            else:
                print(FAIL + f" — {entries.count()} entrées trouvées (attendu 1)")
                results.append(False)

            # Test idempotence : 3 saves supplémentaires → toujours 1 entrée
            for _ in range(3):
                tx.save()
            if CashLedgerEntry.objects.filter(
                portfolio=portfolio,
                reference_type="WALLET_TRANSACTION",
                reference_id=str(tx.id),
            ).count() == 1:
                print(PASS + " — Idempotence : 3 saves supplémentaires → toujours 1 entrée")
                results.append(True)
            else:
                print(FAIL + " — Idempotence cassée : entrées en doublon")
                results.append(False)

        finally:
            transaction.savepoint_rollback(sp)

except Exception as e:
    print(FAIL + f" — Exception inattendue : {e}")
    results.append(False)


# ─────────────────────────────────────────────────────────────────
# CORRECTIF 2 — reconcile_balance (vérifie que le code est correct
#               sans appel broker réel)
# ─────────────────────────────────────────────────────────────────
print("\n─── Correctif 2 : reconcile_balance applique le delta ───")

try:
    from execution.reconciliation import BrokerReconciliationService
    import inspect
    src = inspect.getsource(BrokerReconciliationService.reconcile_balance)
    if "PortfolioAccountingService" in src and "BROKER_IMPORT" in src:
        print(PASS + " — Le code de reconcile_balance appelle bien PortfolioAccountingService")
        results.append(True)
    else:
        print(FAIL + " — Le correctif n'est pas dans reconcile_balance")
        results.append(False)

    if "abs(delta)" in src and "0.01" in src:
        print(PASS + " — Le seuil minimal de 0.01 est en place")
        results.append(True)
    else:
        print(FAIL + " — Le seuil minimal est absent")
        results.append(False)

except Exception as e:
    print(FAIL + f" — Exception : {e}")
    results.append(False)


# ─────────────────────────────────────────────────────────────────
# CORRECTIF 3 — _record_external_only_position : quantité réelle
# ─────────────────────────────────────────────────────────────────
print("\n─── Correctif 3 : Positions importées — quantité réelle ───")

try:
    with transaction.atomic():
        sp = transaction.savepoint()
        try:
            from django.contrib.auth import get_user_model
            from brokers.models import BrokerAccount
            from brokers.services.deriv_sync import _record_external_only_position
            from portfolio.models import Portfolio, Position

            User = get_user_model()
            user2 = User.objects.create_user(username="_verify_pos_tmp", password="x")
            broker2 = BrokerAccount.objects.create(
                user=user2, broker="DERIV", name="test2", mode="DEMO", is_active=True,
            )
            portfolio2 = Portfolio.objects.create(
                user=user2, broker_account=broker2, name="test2",
                base_currency="USD", starting_balance=Decimal("0"),
                current_balance=Decimal("0"), available_cash=Decimal("0"),
                is_default=True, is_active=True,
            )

            payload = {
                "contract_id": 777001,
                "contract_type": "CALL",
                "underlying": "R_100",
                "buy_price": "37.50",
                "current_spot": "1234",
                "is_sold": 0,
            }
            _record_external_only_position(broker2, payload)

            pos = Position.objects.filter(
                portfolio=portfolio2, broker_position_id="777001",
            ).first()

            if pos and pos.quantity == Decimal("37.50"):
                print(PASS + f" — Position importée : quantity={pos.quantity} (= buy_price)")
                results.append(True)
            else:
                qty = pos.quantity if pos else "N/A"
                print(FAIL + f" — quantity={qty} (attendu 37.50)")
                results.append(False)

            if pos and pos.side == "LONG":
                print(PASS + " — Side=LONG pour un contrat CALL")
                results.append(True)
            else:
                side = pos.side if pos else "N/A"
                print(FAIL + f" — side={side} (attendu LONG)")
                results.append(False)

        finally:
            transaction.savepoint_rollback(sp)

except Exception as e:
    print(FAIL + f" — Exception : {e}")
    results.append(False)


# ─────────────────────────────────────────────────────────────────
# CORRECTIF 4 — BrokerExternalRef créé après achat Deriv
# ─────────────────────────────────────────────────────────────────
print("\n─── Correctif 4 : BrokerExternalRef + sync task dans DerivExecutor ───")

try:
    from trading.services.execution.deriv_executor import DerivExecutor
    import inspect
    src = inspect.getsource(DerivExecutor.execute_signal)
    if "BrokerExternalRef" in src and 'kind="CONTRACT"' in src:
        print(PASS + " — BrokerExternalRef.upsert(kind=CONTRACT) présent dans execute_signal")
        results.append(True)
    else:
        print(FAIL + " — BrokerExternalRef.upsert absent de execute_signal")
        results.append(False)

    if "sync_single_deriv_contract_task" in src and "apply_async" in src:
        print(PASS + " — sync_single_deriv_contract_task.apply_async() présent dans execute_signal")
        results.append(True)
    else:
        print(FAIL + " — sync_single_deriv_contract_task.apply_async() absent")
        results.append(False)

except Exception as e:
    print(FAIL + f" — Exception : {e}")
    results.append(False)


# ─────────────────────────────────────────────────────────────────
# RÉSUMÉ
# ─────────────────────────────────────────────────────────────────
n_pass = sum(results)
n_fail = len(results) - n_pass

print("\n" + "=" * 60)
print(f"  RÉSULTAT : {n_pass}/{len(results)} vérifications passées")
if n_fail == 0:
    print("  🎉 Tous les correctifs sont en place !")
else:
    print(f"  ⚠️  {n_fail} problème(s) détecté(s) — voir les ❌ ci-dessus")
print("=" * 60 + "\n")
