from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.text import slugify

from brokers.models import BrokerAccount
from market.models import Asset, Timeframe
from portfolio.models import Portfolio
from strategies.models import Strategy, Signal
from strategies.services.deployment import (
    StrategyDeploymentError,
    StrategyDeploymentService,
)
from trading.services.execution.canonical_signal import CanonicalSignalExecutionService


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

        portfolio = Portfolio.objects.select_related("broker_account").filter(
            pk=options["portfolio_id"],
            user=broker.user,
            broker_account=broker,
            is_active=True,
        ).first()
        if not portfolio:
            raise CommandError("Portfolio actif introuvable ou non lié à ce broker.")

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
            owner=broker.user,
            slug=slugify(f"deriv-{symbol}-{side}-{duration}{duration_unit}"),
            defaults={
                "name": f"Deriv {symbol} {side}",
                "strategy_type": "RULE",
                "asset": asset,
                "timeframe": timeframe,
                "status": "PAPER",
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
        strategy.is_active = True
        strategy.allow_live_execution = broker.mode == "LIVE"
        strategy.parameters = {
            **(strategy.parameters or {}),
            "deriv_duration": duration,
            "deriv_duration_unit": duration_unit,
        }
        strategy.save(update_fields=[
            "is_active",
            "allow_live_execution",
            "parameters",
            "updated_at",
        ])
        try:
            StrategyDeploymentService.activate(
                strategy=strategy,
                user=broker.user,
                portfolio=portfolio,
                auto_execute=False,
            )
        except StrategyDeploymentError as exc:
            raise CommandError(str(exc)) from exc
        strategy.status = broker.mode
        strategy.save(update_fields=["status", "updated_at"])

        signal = Signal.objects.create(
            strategy=strategy,
            user=broker.user,
            candle_time=timezone.now(),
            side=side,
            confidence=0.99,
            price=Decimal("0"),
            status="APPROVED",
            reason="Test Deriv trade command",
        )

        order = CanonicalSignalExecutionService(broker, portfolio).execute(
            signal=signal,
            approved_quantity=amount,
        )

        self.stdout.write(self.style.SUCCESS("Trade Deriv envoyé avec succès"))
        self.stdout.write(f"Order ID: {order.id}")
        self.stdout.write(f"Contract ID: {order.broker_order_id or 'en attente'}")
        self.stdout.write(f"Status: {order.status}")
