from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from brokers.models import BrokerAccount
from market.models import Asset, Timeframe
from portfolio.models import Portfolio
from strategies.models import Strategy, Signal
from trading.services.execution.deriv_executor import DerivExecutor


class Command(BaseCommand):
    help = "Passe un contrat Deriv de test à partir d'un signal local"

    def add_arguments(self, parser):
        parser.add_argument("--broker-id", type=int, required=True)
        parser.add_argument("--portfolio-id", type=int, required=True)
        parser.add_argument("--symbol", type=str, required=True, help="Ex: R_100")
        parser.add_argument("--side", type=str, default="BUY", choices=["BUY", "SELL"])
        parser.add_argument("--amount", type=str, default="10")
        parser.add_argument("--duration", type=int, default=5)
        parser.add_argument("--duration-unit", type=str, default="m")

    def handle(self, *args, **options):
        broker = BrokerAccount.objects.filter(pk=options["broker_id"], broker="DERIV").first()
        if not broker:
            raise CommandError("Broker Deriv introuvable.")

        portfolio = Portfolio.objects.filter(pk=options["portfolio_id"]).first()
        if not portfolio:
            raise CommandError("Portfolio introuvable.")

        symbol = options["symbol"]
        side = options["side"]
        amount = Decimal(options["amount"])
        duration = options["duration"]
        duration_unit = options["duration_unit"]

        asset, _ = Asset.objects.get_or_create(
            symbol=symbol,
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
            slug=slugify(f"deriv-{symbol}-{side}-{duration}{duration_unit}"),
            defaults={
                "name": f"Deriv {symbol} {side}",
                "strategy_type": "RULE",
                "asset": asset,
                "timeframe": timeframe,
                "status": "PAPER" if broker.mode == "PAPER" else "LIVE",
                "is_active": True,
                "is_autonomous": False,
                "allow_live_execution": broker.mode == "LIVE",
                "min_confidence_threshold": 0.1,
                "parameters": {
                    "ml_backend": None,
                    "deriv_duration": duration,
                    "deriv_duration_unit": duration_unit,
                },
            },
        )

        signal = Signal.objects.create(
            strategy=strategy,
            candle_time=portfolio.created_at,
            side=side,
            confidence=0.99,
            price=Decimal("0"),
            status="APPROVED",
            reason="Test Deriv trade command",
        )

        executor = DerivExecutor(broker, portfolio)
        result = executor.execute_signal(signal, amount)

        order = result["order"]
        contract = result["contract"]

        self.stdout.write(self.style.SUCCESS("Trade Deriv envoyé avec succès"))
        self.stdout.write(f"Order ID: {order.id}")
        self.stdout.write(f"Contract ID: {contract.contract_id}")
        self.stdout.write(f"Status: {contract.status}")