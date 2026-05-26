from django.core.management.base import BaseCommand

from core.realtime import RealtimeBroadcastService


class Command(BaseCommand):
    help = "Teste les broadcasts realtime"

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, required=True)
        parser.add_argument("--portfolio-id", type=int, required=True)

    def handle(self, *args, **options):
        user_id = options["user_id"]
        portfolio_id = options["portfolio_id"]

        RealtimeBroadcastService.broadcast_notification(
            user_id=user_id,
            payload={
                "kind": "success",
                "message": "Test notification realtime OK",
            },
        )

        RealtimeBroadcastService.broadcast_portfolio_update(
            portfolio_id=portfolio_id,
            payload={
                "kind": "metrics_refresh",
                "portfolio_id": portfolio_id,
                "balance": "10000.00",
                "available_cash": "8500.00",
                "locked_cash": "1500.00",
                "equity": "10320.55",
                "unrealized_pnl": "320.55",
                "realized_pnl": "1200.00",
                "margin_used": "900.00",
                "drawdown": 2.1,
                "max_drawdown": 5.6,
            },
        )

        self.stdout.write(self.style.SUCCESS("Broadcasts envoyés."))