"""
tests_phase/test_phantom_notional.py
====================================

Débits fantômes au grand livre du portefeuille.

`Order.approved_quantity` n'a pas d'unité garantie : plusieurs chemins y
écrivent un MONTANT EN DEVISE au lieu d'une quantité. L'adaptateur paper
calculait alors `notional = prix × quantité` et produisait un nombre sans
rapport avec l'opération voulue.

Cas réellement survenu en base (ordre 93, portefeuille « Cocody ») :
l'utilisateur engage 20 000 USD sur BTCUSDT à 78 776,62. Le grand livre a
reçu un débit de 1 575 532 400 — 78 776 fois le montant approuvé. Le
portefeuille est passé à −1,59 milliard et n'en est jamais revenu.
"""

from decimal import Decimal

import pytest

from execution.services import (
    MAX_NOTIONAL_OVERSHOOT,
    AccountingBridgeService,
    FillAccountingRefused,
)


class _Order:
    """Ordre minimal : la garde ne lit que ces champs."""

    def __init__(self, approved_notional, approved_quantity=Decimal("1")):
        self.id = 93
        self.symbol = "BTCUSDT"
        self.approved_notional = approved_notional
        self.approved_quantity = approved_quantity


class TestNotionalSanityGuard:

    def test_the_historical_phantom_debit_is_refused(self):
        """Reproduction exacte de l'ordre 93."""
        order = _Order(
            approved_notional=Decimal("20000.00"),
            approved_quantity=Decimal("20000.00"),
        )

        with pytest.raises(FillAccountingRefused) as excinfo:
            AccountingBridgeService._assert_notional_is_sane(
                order, Decimal("1575532400.00"),
            )

        message = str(excinfo.value)
        assert "20000" in message
        assert "unité" in message, "Le motif doit nommer la cause probable."

    def test_a_normal_fill_passes(self):
        order = _Order(approved_notional=Decimal("20000.00"))

        AccountingBridgeService._assert_notional_is_sane(
            order, Decimal("20000.00"),
        )

    def test_ordinary_slippage_passes(self):
        """La garde ne doit pas confondre un écart de marché avec une
        erreur d'unité : elle vise des facteurs de plusieurs milliers."""
        order = _Order(approved_notional=Decimal("20000.00"))

        AccountingBridgeService._assert_notional_is_sane(
            order, Decimal("20600.00"),  # +3 %
        )

    def test_the_tolerance_boundary_is_respected(self):
        order = _Order(approved_notional=Decimal("1000.00"))
        limit = Decimal("1000.00") * MAX_NOTIONAL_OVERSHOOT

        AccountingBridgeService._assert_notional_is_sane(order, limit)

        with pytest.raises(FillAccountingRefused):
            AccountingBridgeService._assert_notional_is_sane(
                order, limit + Decimal("0.01"),
            )

    def test_a_fill_smaller_than_approved_is_never_refused(self):
        """Un remplissage partiel est légitime."""
        order = _Order(approved_notional=Decimal("20000.00"))

        AccountingBridgeService._assert_notional_is_sane(order, Decimal("500.00"))

    def test_without_an_approved_reference_the_guard_stands_down(self):
        """Sans notionnel approuvé, il n'y a rien à quoi comparer :
        refuser systématiquement bloquerait des chemins légitimes."""
        order = _Order(approved_notional=Decimal("0"))

        AccountingBridgeService._assert_notional_is_sane(
            order, Decimal("999999999.00"),
        )


@pytest.mark.django_db
class TestPaperAdapterNotional:
    """L'adaptateur ne doit plus multiplier un montant par un prix."""

    def _order(self, **overrides):
        class _PaperOrder:
            id = 93
            idempotency_key = "k"
            symbol = "BTCUSDT"
            side = "BUY"
            requested_price = Decimal("78776.62")
            limit_price = None
            requested_stake_amount = Decimal("20000.00")
            approved_quantity = Decimal("20000.00")
            approved_notional = Decimal("20000.00")
            estimated_fee = Decimal("0.00")

            class portfolio:
                base_currency = "USD"

        order = _PaperOrder()
        for key, value in overrides.items():
            setattr(order, key, value)
        return order

    def _adapter(self, broker="BINANCE"):
        from execution.adapters.paper import PaperBrokerAdapter

        class _Account:
            pass

        account = _Account()
        account.broker = broker
        adapter = object.__new__(PaperBrokerAdapter)
        adapter.broker_account = account
        return adapter

    def test_the_notional_follows_the_approved_amount(self):
        """Avant : 78 776,62 × 20 000 = 1 575 532 400."""
        adapter = self._adapter()

        result = adapter.submit_order(self._order())

        assert result["fills"][0]["notional"] == Decimal("20000.00")

    def test_the_product_remains_the_last_resort(self):
        """Sans notionnel approuvé, on retombe sur le produit — c'est le
        seul cas où `approved_quantity` est présumée être une quantité."""
        adapter = self._adapter()

        result = adapter.submit_order(
            self._order(approved_notional=Decimal("0"), approved_quantity=Decimal("2")),
        )

        assert result["fills"][0]["notional"] == Decimal("157553.24")

    def test_the_deriv_branch_keeps_using_the_stake(self):
        adapter = self._adapter(broker="DERIV")

        result = adapter.submit_order(self._order())

        assert result["fills"][0]["notional"] == Decimal("20000.00")
        assert result["fills"][0]["quantity"] == Decimal("1")


# ─────────────────────────────────────────────────────────────────────────────
#  La réparation doit survivre à un portefeuille non enregistrable
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestRepairResilience:
    """`Portfolio.save()` appelle `full_clean()`. Un portefeuille rattaché
    au compte broker d'un AUTRE utilisateur devient par là impossible à
    écrire — toute mise à jour comptable y est bloquée, pas seulement la
    réparation. La commande doit le signaler et poursuivre, pas abandonner
    les autres portefeuilles en route.
    """

    def test_an_unsavable_portfolio_does_not_abort_the_run(self, db, capsys):
        from io import StringIO

        from django.contrib.auth import get_user_model
        from django.core.management import call_command

        from portfolio.models import Portfolio
        from portfolio.services_onboarding import PaperOnboardingService

        User = get_user_model()
        owner = User.objects.create_user(
            username="prop", email="prop@leotrade.test", password="StrongPass123!",
        )
        stranger = User.objects.create_user(
            username="tiers", email="tiers@leotrade.test", password="StrongPass123!",
        )
        healthy = PaperOnboardingService.provision(owner)
        foreign = PaperOnboardingService.provision(stranger)

        # On force le rattachement croisé en contournant full_clean, comme
        # l'a fait le chemin qui a produit la donnée réelle.
        Portfolio.objects.filter(pk=healthy.pk).update(
            broker_account=foreign.broker_account,
        )

        output = StringIO()
        # Ne doit pas lever, même si ce portefeuille est inenregistrable.
        call_command("repair_phantom_notional", "--positions", stdout=output)

        assert "Aucun débit fantôme" in output.getvalue()

    def test_the_blockage_is_reported_not_swallowed(self, db):
        """Un champ de solde périmé sans explication serait pire qu'une
        erreur : on croirait le chiffre à jour."""
        from io import StringIO

        from django.contrib.auth import get_user_model
        from django.core.management import call_command

        from portfolio.models import Portfolio
        from portfolio.services_onboarding import PaperOnboardingService

        User = get_user_model()
        owner = User.objects.create_user(
            username="prop2", email="prop2@leotrade.test", password="StrongPass123!",
        )
        stranger = User.objects.create_user(
            username="tiers2", email="tiers2@leotrade.test", password="StrongPass123!",
        )
        broken = PaperOnboardingService.provision(owner)
        foreign = PaperOnboardingService.provision(stranger)
        Portfolio.objects.filter(pk=broken.pk).update(
            broker_account=foreign.broker_account,
        )

        from portfolio.management.commands.repair_phantom_notional import Command

        command = Command()
        command.stdout = StringIO()
        command.style = type("S", (), {"ERROR": str, "SUCCESS": str, "WARNING": str})()
        command._refresh({broken.pk}, "solde")

        printed = command.stdout.getvalue()
        assert "IMPOSSIBLE" in printed
        assert "broker_account" in printed
