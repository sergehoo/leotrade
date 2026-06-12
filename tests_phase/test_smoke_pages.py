"""Smoke test — rend toutes les pages touchées par le chantier UI/API en cours.

Lancement : python manage.py test tests_phase.test_smoke_pages
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

PAGES = [
    "dashboard",
    "asset-list",
    "market-assets-api",
    "strategy-list",
    "strategy-list-api",
    "backtest-list",
    "wallet-dashboard",
    "wallet-transfer",
    "transfer-history",
    "trading:signal-list",
    "trading:signal-list-api",
    "trading:order-list",
    "trading:risk-monitor",
    "trading:risk-monitor-api",
    "trading:learning-monitor",
    "trading:learning-monitor-api",
    "trading:trade-idea-list",
    "trading:hedge-fund-dashboard",
]


class SmokePagesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="smoke", email="smoke@test.io", password="x" * 12
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_pages_render(self):
        for name in PAGES:
            with self.subTest(page=name):
                url = reverse(name)
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 200, f"{name} ({url}) -> {resp.status_code}")

    def test_live_data_api(self):
        resp = self.client.get(reverse("fund-dashboard-live"))
        self.assertEqual(resp.status_code, 200)

    def test_transfer_post_invalid_amount(self):
        resp = self.client.post(
            reverse("wallet-transfer"),
            {"direction": "to_portfolio", "portfolio_id": "", "amount": "abc"},
        )
        self.assertEqual(resp.status_code, 200)  # re-render avec message d'erreur

    def test_transfer_roundtrip(self):
        from brokers.models import BrokerAccount
        from portfolio.models import Portfolio
        from wallet.models import Wallet

        wallet, _ = Wallet.objects.get_or_create(
            user=self.user, defaults={"currency": "USD"}
        )
        Wallet.objects.filter(pk=wallet.pk).update(available_balance=Decimal("1000"))
        broker = BrokerAccount.objects.create(
            user=self.user, name="Paper", broker="BINANCE", mode="PAPER"
        )
        portfolio = Portfolio.objects.create(
            user=self.user,
            broker_account=broker,
            name="Smoke PF",
            is_active=True,
            is_default=True,
        )

        resp = self.client.post(
            reverse("wallet-transfer"),
            {
                "direction": "to_portfolio",
                "portfolio_id": str(portfolio.pk),
                "amount": "250",
            },
        )
        self.assertEqual(resp.status_code, 302)

        wallet.refresh_from_db()
        portfolio.refresh_from_db()
        self.assertEqual(wallet.available_balance, Decimal("750"))
        self.assertEqual(portfolio.available_cash, Decimal("250"))

        resp = self.client.post(
            reverse("wallet-transfer"),
            {
                "direction": "to_wallet",
                "portfolio_id": str(portfolio.pk),
                "amount": "100",
            },
        )
        self.assertEqual(resp.status_code, 302)

        wallet.refresh_from_db()
        portfolio.refresh_from_db()
        self.assertEqual(wallet.available_balance, Decimal("850"))
        self.assertEqual(portfolio.available_cash, Decimal("150"))


class ChartPageTest(TestCase):
    """Page chart : bougies réelles + overlays des positions de l'utilisateur."""

    @classmethod
    def setUpTestData(cls):
        from decimal import Decimal

        from brokers.models import BrokerAccount
        from market.models import Asset, Timeframe
        from portfolio.models import Portfolio, Position

        cls.user = get_user_model().objects.create_user(
            username="chartuser", email="chart@test.io", password="x" * 12
        )
        cls.asset = Asset.objects.create(
            symbol="R_100", name="Volatility 100", asset_class="SYNTHETIC",
            exchange="DERIV", is_active=True,
        )
        Timeframe.objects.get_or_create(code="1m", defaults={"minutes": 1})
        broker = BrokerAccount.objects.create(
            user=cls.user, name="Paper", broker="BINANCE", mode="PAPER",
        )
        portfolio = Portfolio.objects.create(
            user=cls.user, broker_account=broker, name="Chart PF", is_active=True,
        )
        Position.objects.create(
            portfolio=portfolio, broker_account=broker, asset=cls.asset,
            symbol="R_100", side="LONG",
            quantity=Decimal("1"), entry_price=Decimal("100"),
            average_entry_price=Decimal("100"), current_price=Decimal("101"),
            stop_loss=Decimal("95"), take_profit=Decimal("110"),
            status="OPEN", source="MANUAL",
        )

    def test_chart_page_includes_position_overlays(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("asset-chart", args=[self.asset.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["open_positions_count"], 1)
        self.assertIn("position ouverte", resp.content.decode())
        positions = resp.context["positions_json"]
        self.assertIn('"stop_loss": 95.0', positions)
        self.assertIn('"take_profit": 110.0', positions)
