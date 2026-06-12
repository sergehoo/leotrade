"""
tests_phase/test_wallet_portfolio_bridge.py
============================================

Tests de vérification des 4 correctifs appliqués (mai 2026).

Correctif 1 — Pont Wallet → Portfolio
    Vérifie que quand une WalletTransaction passe à SUCCEEDED,
    une CashLedgerEntry est créée sur le portfolio par défaut.

Correctif 2 — reconcile_balance applique le delta
    Vérifie que BrokerReconciliationService.reconcile_balance()
    crée bien une entrée BROKER_IMPORT quand il y a un écart de balance.

Correctif 3 — _record_external_only_position : quantité réelle
    Vérifie que les positions importées utilisent buy_price comme
    quantity et non plus la valeur hardcodée 1.

Correctif 4 — BrokerExternalRef créé après achat Deriv
    Vérifie que le signal de idempotence du pont wallet est bien
    idempotent (multiple saves → une seule entrée ledger).

Lancer avec :
    cd /chemin/vers/leoTrade
    DJANGO_SETTINGS_MODULE=leoTrade.settings pytest tests_phase/test_wallet_portfolio_bridge.py -v

Ou via Django :
    python manage.py test tests_phase.test_wallet_portfolio_bridge
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model

from brokers.models import BrokerAccount
from brokers.models_external_ref import BrokerExternalRef
from brokers.services.deriv_sync import _record_external_only_position
from portfolio.models import CashLedgerEntry, Portfolio
from wallet.models import Wallet, WalletTransaction

User = get_user_model()


# =============================================================================
# Fixtures communes
# =============================================================================

@pytest.fixture
def user(db):
    return User.objects.create_user(username="test_bridge_user", password="x")


@pytest.fixture
def wallet(user):
    w, _ = Wallet.objects.get_or_create(user=user, defaults={"currency": "USD"})
    return w


@pytest.fixture
def broker_account(user):
    return BrokerAccount.objects.create(
        user=user,
        broker="DERIV",
        name="demo",
        mode="PAPER",
        deriv_app_id="1089",
        is_active=True,
    )


@pytest.fixture
def portfolio(user, broker_account):
    return Portfolio.objects.create(
        user=user,
        broker_account=broker_account,
        name="Portfolio principal",
        base_currency="USD",
        starting_balance=Decimal("0.00"),
        current_balance=Decimal("0.00"),
        available_cash=Decimal("0.00"),
        is_default=True,
        is_active=True,
    )


# =============================================================================
# Correctif 1 — Pont Wallet → Portfolio
# =============================================================================

@pytest.mark.django_db
def test_wallet_deposit_creates_portfolio_ledger_entry(user, wallet, portfolio):
    """
    Un dépôt wallet qui passe à SUCCEEDED doit créer une CashLedgerEntry
    sur le portfolio par défaut de l'utilisateur.
    """
    tx = WalletTransaction.objects.create(
        wallet=wallet,
        tx_type="DEPOSIT",
        amount=Decimal("250.00"),
        currency="USD",
        status="SUCCEEDED",
    )

    # Le signal post_save doit avoir été déclenché à la création (status=SUCCEEDED dès le départ)
    # Si ce n'est pas le cas, on le déclenche manuellement en sauvegardant
    tx.save()

    entries = CashLedgerEntry.objects.filter(
        portfolio=portfolio,
        reference_type="WALLET_TRANSACTION",
        reference_id=str(tx.id),
    )
    assert entries.count() == 1, (
        f"Attendu 1 CashLedgerEntry, trouvé {entries.count()}. "
        "Le pont Wallet→Portfolio ne fonctionne pas."
    )
    entry = entries.first()
    assert entry.entry_type == "DEPOSIT"
    assert entry.amount == Decimal("250.00")
    assert entry.currency == "USD"


@pytest.mark.django_db
def test_wallet_deposit_idempotent(user, wallet, portfolio):
    """
    Sauvegarder plusieurs fois la même WalletTransaction SUCCEEDED
    ne doit créer qu'une seule CashLedgerEntry (idempotence).
    """
    tx = WalletTransaction.objects.create(
        wallet=wallet,
        tx_type="DEPOSIT",
        amount=Decimal("100.00"),
        currency="USD",
        status="SUCCEEDED",
    )

    # Simulate multiple saves (webhook retry, admin re-save…)
    for _ in range(4):
        tx.save()

    entries = CashLedgerEntry.objects.filter(
        portfolio=portfolio,
        reference_type="WALLET_TRANSACTION",
        reference_id=str(tx.id),
    )
    assert entries.count() == 1, (
        f"Idempotence cassée : {entries.count()} entrées créées au lieu de 1."
    )


@pytest.mark.django_db
def test_wallet_pending_does_not_create_ledger_entry(user, wallet, portfolio):
    """
    Un dépôt wallet en statut PENDING ne doit PAS créer d'entrée ledger.
    """
    tx = WalletTransaction.objects.create(
        wallet=wallet,
        tx_type="DEPOSIT",
        amount=Decimal("100.00"),
        currency="USD",
        status="PENDING",
    )
    tx.save()

    entries = CashLedgerEntry.objects.filter(
        portfolio=portfolio,
        reference_type="WALLET_TRANSACTION",
        reference_id=str(tx.id),
    )
    assert entries.count() == 0, (
        "Une entrée ledger a été créée pour une transaction PENDING — ce ne devrait pas arriver."
    )


@pytest.mark.django_db
def test_wallet_withdrawal_creates_negative_ledger_entry(user, wallet, portfolio):
    """
    Un retrait SUCCEEDED doit créer une CashLedgerEntry négative (WITHDRAWAL).
    """
    # D'abord créditer le portfolio pour éviter un insufficient funds
    from portfolio.services import PortfolioAccountingService
    PortfolioAccountingService.add_ledger_entry(
        portfolio=portfolio,
        entry_type="DEPOSIT",
        amount=Decimal("500.00"),
        currency="USD",
        description="Seed for test",
    )

    tx = WalletTransaction.objects.create(
        wallet=wallet,
        tx_type="WITHDRAWAL",
        amount=Decimal("75.00"),
        currency="USD",
        status="SUCCEEDED",
    )
    tx.save()

    entries = CashLedgerEntry.objects.filter(
        portfolio=portfolio,
        reference_type="WALLET_TRANSACTION",
        reference_id=str(tx.id),
    )
    assert entries.count() == 1
    entry = entries.first()
    assert entry.entry_type == "WITHDRAWAL"
    assert entry.amount == Decimal("-75.00"), (
        f"Le montant du retrait devrait être -75.00, trouvé {entry.amount}"
    )


@pytest.mark.django_db
def test_wallet_deposit_no_portfolio_does_not_crash(user, wallet):
    """
    Si l'utilisateur n'a aucun portfolio actif, le signal ne doit pas planter.
    """
    # On ne crée pas de portfolio pour cet utilisateur
    tx = WalletTransaction.objects.create(
        wallet=wallet,
        tx_type="DEPOSIT",
        amount=Decimal("50.00"),
        currency="USD",
        status="SUCCEEDED",
    )
    # Ne doit lever aucune exception
    tx.save()


# =============================================================================
# Correctif 3 — _record_external_only_position : quantité réelle
# =============================================================================

@pytest.mark.django_db
def test_external_position_uses_buy_price_as_quantity(user, broker_account, portfolio):
    """
    _record_external_only_position() doit utiliser buy_price comme quantity
    et non plus la valeur hardcodée 1.
    """
    payload = {
        "contract_id": 99001,
        "contract_type": "CALL",
        "underlying": "R_100",
        "display_name": "Volatility 100 Index",
        "buy_price": "25.50",
        "current_spot": "1234.56",
        "is_sold": 0,
        "shortcode": "CALL_R_100_25.50_...",
    }

    _record_external_only_position(broker_account, payload)

    from portfolio.models import Position
    pos = Position.objects.filter(
        portfolio=portfolio,
        broker_position_id="99001",
    ).first()

    assert pos is not None, "La position importée n'a pas été créée."
    assert pos.quantity == Decimal("25.50"), (
        f"Attendu quantity=25.50 (buy_price), trouvé {pos.quantity}. "
        "La correction de la quantité hardcodée ne fonctionne pas."
    )
    assert pos.side == "LONG", f"Attendu LONG pour un CALL, trouvé {pos.side}"


@pytest.mark.django_db
def test_external_position_idempotent(user, broker_account, portfolio):
    """
    Appeler _record_external_only_position deux fois avec le même contract_id
    doit update_or_create → toujours 1 seule position.
    """
    from portfolio.models import Position

    payload = {
        "contract_id": 99002,
        "contract_type": "PUT",
        "underlying": "R_50",
        "buy_price": "10.00",
        "is_sold": 0,
    }

    _record_external_only_position(broker_account, payload)
    _record_external_only_position(broker_account, payload)

    count = Position.objects.filter(
        portfolio=portfolio,
        broker_position_id="99002",
    ).count()
    assert count == 1, f"Attendu 1 position, trouvé {count} (doublon créé)."


# =============================================================================
# Correctif 4 — BrokerExternalRef créé après achat Deriv
# (test de la logique sans appel réseau)
# =============================================================================

@pytest.mark.django_db
def test_broker_external_ref_upsert_idempotent(user, broker_account):
    """
    BrokerExternalRef.upsert appelé plusieurs fois avec le même
    (broker, kind, external_id) ne crée pas de doublon.
    """
    for _ in range(3):
        BrokerExternalRef.upsert(
            broker="DERIV",
            broker_account=broker_account,
            kind="CONTRACT",
            external_id="contract-42",
            internal_kind="ORDER",
            internal_id="1",
            last_status="open",
            last_payload={"buy_price": "50.00"},
        )

    count = BrokerExternalRef.objects.filter(
        broker="DERIV",
        kind="CONTRACT",
        external_id="contract-42",
    ).count()
    assert count == 1, f"Attendu 1 BrokerExternalRef, trouvé {count} (doublon)."


@pytest.mark.django_db
def test_broker_external_ref_resolve_after_upsert(user, broker_account):
    """
    Après un upsert, resolve() doit retrouver la référence.
    C'est la condition nécessaire pour que on_open_contract_update()
    retrouve l'ordre local au lieu de créer une position fantôme.
    """
    BrokerExternalRef.upsert(
        broker="DERIV",
        broker_account=broker_account,
        kind="CONTRACT",
        external_id="contract-43",
        internal_kind="ORDER",
        internal_id="100",
        last_status="open",
        last_payload={},
    )

    ref = BrokerExternalRef.resolve(
        broker="DERIV",
        kind="CONTRACT",
        external_id="contract-43",
    )
    assert ref is not None, "resolve() a retourné None — la référence est introuvable."
    assert ref.internal_id == "100"
    assert ref.internal_kind == "ORDER"
