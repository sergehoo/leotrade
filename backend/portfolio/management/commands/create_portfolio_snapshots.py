from django.core.management.base import BaseCommand
from portfolio.models import Portfolio
from portfolio.services import PortfolioService


class Command(BaseCommand):
    help = "Crée des snapshots pour tous les portfolios actifs"

    def handle(self, *args, **options):
        portfolios = Portfolio.objects.filter(is_active=True)

        total = 0
        for portfolio in portfolios:
            try:
                PortfolioService.refresh_portfolio_metrics(portfolio)
                PortfolioService.create_snapshot(portfolio)
                total += 1
                self.stdout.write(self.style.SUCCESS(f"Snapshot créé pour {portfolio.name}"))
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"Erreur sur {portfolio.name}: {exc}"))

        self.stdout.write(self.style.SUCCESS(f"Terminé. {total} snapshots créés."))