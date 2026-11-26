"""Rapproche les soldes des portefeuilles avec leur grand livre.

    python manage.py reconcile_wallets
    python manage.py reconcile_wallets --only-unbalanced

Sort en code 1 si au moins un portefeuille est déséquilibré, pour qu'un
ordonnanceur ou une CI puisse en faire un signal.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand

from wallet.services_reconciliation import WalletReconciliationService


class Command(BaseCommand):
    help = "Rapproche le solde de chaque portefeuille avec son grand livre."

    def add_arguments(self, parser):
        parser.add_argument(
            "--only-unbalanced",
            action="store_true",
            help="N'afficher que les portefeuilles déséquilibrés.",
        )

    def handle(self, *args, **options):
        results = WalletReconciliationService.reconcile_all()
        unbalanced = [r for r in results if not r.is_balanced]

        for result in results:
            if options["only_unbalanced"] and result.is_balanced:
                continue
            write = self.stdout.write
            style = self.style.SUCCESS if result.is_balanced else self.style.ERROR
            write(style(result.summary()))
            for item in result.breaks:
                write(f"    écriture #{item.entry_id} : {item.detail}")

        self.stdout.write("")
        if unbalanced:
            total = sum((r.unexplained_amount for r in unbalanced), Decimal("0.00"))
            self.stdout.write(self.style.ERROR(
                f"{len(unbalanced)}/{len(results)} portefeuille(s) déséquilibré(s), "
                f"{total} non justifié(s)"
            ))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS(
            f"{len(results)} portefeuille(s) rapproché(s), aucun écart."
        ))
