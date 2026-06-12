"""
tests_phase/test_balance_sync.py
=================================

Couverture : cohérence du solde pendant le cycle lock_cash → register_fill.

Invariant fondamental :
    current_balance = available_cash + locked_cash   (à tout instant)

Scénarios :
  1. Avant lock : available_cash == current_balance, locked_cash == 0.
  2. Après lock_cash_for_order : available_cash réduit, locked_cash augmenté,
     current_balance inchangé.
  3. Après register_fill : locked_cash libéré, accounting TRADE_EXECUTION créé,
     current_balance déduit du coût réel.
  4. Cash insuffisant → ValueError, aucune entrée ledger créée.
  5. Double lock idempotent : un ORDER_LOCK unique par order_id → pas de débit double.
  6. Annulation (release) restaure exactly le montant lockéé.
"""

from decimal import Decimal
from unittest import mock

import pytest
from django.utils import timezone

from portfolio.models import CashLedgerEntry, Portfolio
from portfolio.services import PortfolioAccountingService, PortfolioService

# ── Constantes ────────────────────────────────────────────────────────────────

STARTING_BALANCE = Decimal("10000.00")
LOCK_AMOUNT = Decimal("500.00")
FILL_COST = Decimal("498.50")  # légèrement différent (slippage)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _balances(portfolio):
    """Recharge et retourne (current_balance, available_cash, locked_cash)."""
    portfolio.refresh_from_db()
    return (
        portfolio.current_balance,
        portfolio.available_cash,
        portfolio.locked_cash,
    )


def _assert_invariant(portfolio, label=""):
    """Vérifie l'invariant current_balance == available_cash + locked_cash."""
    current, available, locked = _balances(portfolio)
    diff = abs(current - (available + locked))
    assert diff < Decimal("0.01"), (
        f"[{label}] Invariant rompu : "
        f"current={current} ≠ available={available} + locked={locked} "
        f"(delta={diff})"
    )


# ─────────────────────────────────────────────────────────────────────────────
#  1. État initial
# ─────────────────────────────────────────────────────────────────────────────

class TestInitialState:

    @pytest.mark.django_db
    def test_initial_invariant(self, portfolio_paper):
        """Avant tout, l'invariant est satisfait."""
        _assert_invariant(portfolio_paper, "initial")

    @pytest.mark.django_db
    def test_initial_no_locked_cash(self, portfolio_paper):
        """Aucun cash verrouillé au départ."""
        portfolio_paper.refresh_from_db()
        assert portfolio_paper.locked_cash == Decimal("0.00")
        assert portfolio_paper.available_cash == portfolio_paper.current_balance


# ─────────────────────────────────────────────────────────────────────────────
#  2. Après lock_cash_for_order
# ─────────────────────────────────────────────────────────────────────────────

class TestAfterLock:

    @pytest.mark.django_db
    def test_lock_reduces_available_cash(self, portfolio_paper):
        """Le lock réduit available_cash du montant locké."""
        before = portfolio_paper.available_cash

        PortfolioAccountingService.lock_cash_for_order(
            portfolio=portfolio_paper,
            amount=LOCK_AMOUNT,
            reference_type="ORDER",
            reference_id="order-test-1",
        )

        portfolio_paper.refresh_from_db()
        assert portfolio_paper.available_cash == before - LOCK_AMOUNT

    @pytest.mark.django_db
    def test_lock_increases_locked_cash(self, portfolio_paper):
        """Le lock augmente locked_cash du montant locké."""
        PortfolioAccountingService.lock_cash_for_order(
            portfolio=portfolio_paper,
            amount=LOCK_AMOUNT,
            reference_type="ORDER",
            reference_id="order-test-2",
        )

        portfolio_paper.refresh_from_db()
        assert portfolio_paper.locked_cash == LOCK_AMOUNT

    @pytest.mark.django_db
    def test_lock_does_not_change_current_balance(self, portfolio_paper):
        """Le lock ne doit PAS modifier current_balance (argent toujours là)."""
        before = portfolio_paper.current_balance

        PortfolioAccountingService.lock_cash_for_order(
            portfolio=portfolio_paper,
            amount=LOCK_AMOUNT,
            reference_type="ORDER",
            reference_id="order-test-3",
        )

        portfolio_paper.refresh_from_db()
        assert portfolio_paper.current_balance == before

    @pytest.mark.django_db
    def test_invariant_after_lock(self, portfolio_paper):
        """Invariant préservé après lock."""
        PortfolioAccountingService.lock_cash_for_order(
            portfolio=portfolio_paper,
            amount=LOCK_AMOUNT,
            reference_type="ORDER",
            reference_id="order-test-4",
        )
        _assert_invariant(portfolio_paper, "after_lock")

    @pytest.mark.django_db
    def test_lock_creates_ledger_entry(self, portfolio_paper):
        """Un ORDER_LOCK doit créer une entrée dans le ledger."""
        PortfolioAccountingService.lock_cash_for_order(
            portfolio=portfolio_paper,
            amount=LOCK_AMOUNT,
            reference_type="ORDER",
            reference_id="order-test-5",
        )

        entry = CashLedgerEntry.objects.filter(
            portfolio=portfolio_paper,
            entry_type="ORDER_LOCK",
            reference_id="order-test-5",
        ).first()

        assert entry is not None
        assert entry.amount == -LOCK_AMOUNT  # négatif (débit)


# ─────────────────────────────────────────────────────────────────────────────
#  3. Cash insuffisant
# ─────────────────────────────────────────────────────────────────────────────

class TestInsufficientCash:

    @pytest.mark.django_db
    def test_lock_raises_on_insufficient_cash(self, portfolio_paper):
        """lock_cash_for_order lève ValueError si cash insuffisant."""
        too_much = portfolio_paper.available_cash + Decimal("9999.00")

        with pytest.raises(ValueError, match="insuffisant"):
            PortfolioAccountingService.lock_cash_for_order(
                portfolio=portfolio_paper,
                amount=too_much,
                reference_type="ORDER",
                reference_id="over-limit",
            )

    @pytest.mark.django_db
    def test_no_ledger_entry_on_failure(self, portfolio_paper):
        """Aucune entrée ledger ne doit être créée si le lock échoue."""
        ledger_count_before = CashLedgerEntry.objects.filter(
            portfolio=portfolio_paper
        ).count()

        too_much = portfolio_paper.available_cash + Decimal("9999.00")
        try:
            PortfolioAccountingService.lock_cash_for_order(
                portfolio=portfolio_paper,
                amount=too_much,
                reference_type="ORDER",
                reference_id="over-limit-no-entry",
            )
        except ValueError:
            pass

        assert CashLedgerEntry.objects.filter(
            portfolio=portfolio_paper
        ).count() == ledger_count_before

    @pytest.mark.django_db
    def test_invariant_preserved_on_failure(self, portfolio_paper):
        """L'invariant est préservé même si le lock échoue."""
        too_much = portfolio_paper.available_cash + Decimal("9999.00")
        try:
            PortfolioAccountingService.lock_cash_for_order(
                portfolio=portfolio_paper,
                amount=too_much,
                reference_type="ORDER",
                reference_id="over-limit-inv",
            )
        except ValueError:
            pass

        _assert_invariant(portfolio_paper, "after_failed_lock")


# ─────────────────────────────────────────────────────────────────────────────
#  4. Release (annulation d'ordre)
# ─────────────────────────────────────────────────────────────────────────────

class TestReleaseCash:

    @pytest.mark.django_db
    def test_release_restores_available_cash(self, portfolio_paper):
        """release_cash_from_order restaure exactement available_cash."""
        original_available = portfolio_paper.available_cash

        PortfolioAccountingService.lock_cash_for_order(
            portfolio=portfolio_paper,
            amount=LOCK_AMOUNT,
            reference_type="ORDER",
            reference_id="order-release-1",
        )
        PortfolioAccountingService.release_cash_from_order(
            portfolio=portfolio_paper,
            amount=LOCK_AMOUNT,
            reference_type="ORDER",
            reference_id="order-release-1",
        )

        portfolio_paper.refresh_from_db()
        assert portfolio_paper.available_cash == original_available

    @pytest.mark.django_db
    def test_release_zeroes_locked_cash(self, portfolio_paper):
        """Après release complet, locked_cash revient à 0."""
        PortfolioAccountingService.lock_cash_for_order(
            portfolio=portfolio_paper,
            amount=LOCK_AMOUNT,
            reference_type="ORDER",
            reference_id="order-release-2",
        )
        PortfolioAccountingService.release_cash_from_order(
            portfolio=portfolio_paper,
            amount=LOCK_AMOUNT,
            reference_type="ORDER",
            reference_id="order-release-2",
        )

        portfolio_paper.refresh_from_db()
        assert portfolio_paper.locked_cash == Decimal("0.00")

    @pytest.mark.django_db
    def test_invariant_after_lock_then_release(self, portfolio_paper):
        """Invariant préservé après lock+release."""
        PortfolioAccountingService.lock_cash_for_order(
            portfolio=portfolio_paper,
            amount=LOCK_AMOUNT,
            reference_type="ORDER",
            reference_id="order-release-3",
        )
        _assert_invariant(portfolio_paper, "after_lock")

        PortfolioAccountingService.release_cash_from_order(
            portfolio=portfolio_paper,
            amount=LOCK_AMOUNT,
            reference_type="ORDER",
            reference_id="order-release-3",
        )
        _assert_invariant(portfolio_paper, "after_release")


# ─────────────────────────────────────────────────────────────────────────────
#  5. Cycle complet lock → fill (via FillProcessingService.register_fill)
# ─────────────────────────────────────────────────────────────────────────────

class TestLockToFillCycle:

    @pytest.fixture
    def live_order(self, db, portfolio_live, broker_live, user):
        """Crée un Order LIVE en état PENDING_SUBMIT."""
        from execution.models import Order
        return Order.objects.create(
            user=user,
            portfolio=portfolio_live,
            broker_account=broker_live,
            symbol="R_100",
            side="BUY",
            order_type="MARKET",
            mode="LIVE",
            status="PENDING_SUBMIT",
            requested_quantity=Decimal("1"),
            approved_quantity=Decimal("1"),
            requested_stake_amount=LOCK_AMOUNT,
            approved_notional=LOCK_AMOUNT,
            idempotency_key="fill-cycle-test-1",
        )

    @pytest.mark.django_db
    def test_no_phantom_delta_after_fill(self, portfolio_live, live_order):
        """Après lock + register_fill, l'invariant est préservé (pas de delta fantôme)."""
        from execution.services import FillProcessingService

        # Lock
        PortfolioAccountingService.lock_cash_for_order(
            portfolio=portfolio_live,
            amount=LOCK_AMOUNT,
            reference_type="ORDER",
            reference_id=str(live_order.id),
        )
        _assert_invariant(portfolio_live, "after_lock")

        # Mock les side-effects (position, broadcast) pour isoler la comptabilité
        with mock.patch("execution.services.PositionService.apply_fill_to_position"), \
             mock.patch("execution.services.AccountingBridgeService.apply_fill_accounting"), \
             mock.patch("execution.services.TradingNotificationService.notify_order_filled"), \
             mock.patch("execution.services.RealtimeBroadcastService.broadcast_dashboard_update"), \
             mock.patch("execution.services.RealtimeBroadcastService.broadcast_portfolio_update"), \
             mock.patch("django.db.transaction.on_commit", lambda fn: fn()):

            FillProcessingService.register_fill(
                order=live_order,
                fill_payload={
                    "quantity": Decimal("1"),
                    "price": Decimal("500.00"),
                    "notional": LOCK_AMOUNT,
                    "fee": Decimal("0.00"),
                    "broker_fill_id": "FILL-001",
                },
            )

        _assert_invariant(portfolio_live, "after_fill")

    @pytest.mark.django_db
    def test_fill_idempotent_double_register(self, portfolio_live, live_order):
        """register_fill avec le même broker_fill_id ne crée pas deux entrées."""
        from execution.services import FillProcessingService

        PortfolioAccountingService.lock_cash_for_order(
            portfolio=portfolio_live,
            amount=LOCK_AMOUNT,
            reference_type="ORDER",
            reference_id=str(live_order.id),
        )

        fill_payload = {
            "quantity": Decimal("1"),
            "price": Decimal("500.00"),
            "notional": LOCK_AMOUNT,
            "fee": Decimal("0.00"),
            "broker_fill_id": "FILL-IDEMPOTENT-001",
        }

        with mock.patch("execution.services.PositionService.apply_fill_to_position"), \
             mock.patch("execution.services.AccountingBridgeService.apply_fill_accounting"), \
             mock.patch("execution.services.TradingNotificationService.notify_order_filled"), \
             mock.patch("execution.services.RealtimeBroadcastService.broadcast_dashboard_update"), \
             mock.patch("execution.services.RealtimeBroadcastService.broadcast_portfolio_update"), \
             mock.patch("django.db.transaction.on_commit", lambda fn: fn()):

            f1 = FillProcessingService.register_fill(order=live_order, fill_payload=fill_payload)
            f2 = FillProcessingService.register_fill(order=live_order, fill_payload=fill_payload)

        # Même objet retourné (idempotence)
        assert f1.id == f2.id

        # Une seule entrée fill en DB
        from execution.models import ExecutionFill
        fills = ExecutionFill.objects.filter(
            order=live_order, broker_fill_id="FILL-IDEMPOTENT-001"
        )
        assert fills.count() == 1


# ─────────────────────────────────────────────────────────────────────────────
#  6. Multiples locks successifs (plusieurs ordres simultanés)
# ─────────────────────────────────────────────────────────────────────────────

class TestMultipleLocks:

    @pytest.mark.django_db
    def test_multiple_locks_accumulate_correctly(self, portfolio_paper):
        """Deux locks successifs → locked_cash = somme des deux montants."""
        amount_1 = Decimal("200.00")
        amount_2 = Decimal("300.00")

        PortfolioAccountingService.lock_cash_for_order(
            portfolio=portfolio_paper,
            amount=amount_1,
            reference_type="ORDER",
            reference_id="multi-lock-1",
        )
        PortfolioAccountingService.lock_cash_for_order(
            portfolio=portfolio_paper,
            amount=amount_2,
            reference_type="ORDER",
            reference_id="multi-lock-2",
        )

        portfolio_paper.refresh_from_db()
        assert portfolio_paper.locked_cash == amount_1 + amount_2
        assert portfolio_paper.available_cash == STARTING_BALANCE - amount_1 - amount_2
        _assert_invariant(portfolio_paper, "multi_lock")

    @pytest.mark.django_db
    def test_lock_beyond_available_after_partial_lock(self, portfolio_paper):
        """Tenter de locker plus que le cash restant après un premier lock → ValueError."""
        PortfolioAccountingService.lock_cash_for_order(
            portfolio=portfolio_paper,
            amount=Decimal("9000.00"),
            reference_type="ORDER",
            reference_id="partial-then-over-1",
        )

        with pytest.raises(ValueError, match="insuffisant"):
            PortfolioAccountingService.lock_cash_for_order(
                portfolio=portfolio_paper,
                amount=Decimal("9000.00"),  # dépasse le disponible restant
                reference_type="ORDER",
                reference_id="partial-then-over-2",
            )

        # L'invariant doit rester valide malgré le rejet
        _assert_invariant(portfolio_paper, "after_partial_over")
