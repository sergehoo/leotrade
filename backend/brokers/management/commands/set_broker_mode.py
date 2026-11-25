"""
brokers/management/commands/set_broker_mode.py
==============================================

Bascule rapidement un BrokerAccount entre PAPER et LIVE.

Pourquoi ce helper
------------------
Quand un compte Deriv est en mode PAPER, l'ExecutionOrchestrator route les
ordres vers ``PaperBrokerAdapter`` qui simule un fill localement et ne
contacte JAMAIS Deriv. C'est utile pour les tests offline mais piège
beaucoup d'utilisateurs qui pensent que leur ordre a été passé.

Usage
-----
    python manage.py set_broker_mode --account-id 12 --mode LIVE
    python manage.py set_broker_mode --user serge@example.com --broker DERIV --mode LIVE
    python manage.py set_broker_mode --list
"""

from django.core.management.base import BaseCommand, CommandError

from brokers.models import BrokerAccount


class Command(BaseCommand):
    help = "Affiche ou modifie le mode (PAPER/LIVE) d'un BrokerAccount."

    def add_arguments(self, parser):
        parser.add_argument("--account-id", type=int, default=None,
                            help="ID du BrokerAccount à modifier.")
        parser.add_argument("--user", type=str, default=None,
                            help="Email ou username du propriétaire (filtre).")
        parser.add_argument("--broker", type=str, default=None,
                            help="Code broker (DERIV, BINANCE, MT5).")
        parser.add_argument("--mode", type=str, default=None,
                            choices=["PAPER", "LIVE"],
                            help="Nouveau mode à appliquer.")
        parser.add_argument("--list", action="store_true",
                            help="Liste les comptes au lieu de modifier.")

    def handle(self, *args, **options):
        if options["list"]:
            qs = BrokerAccount.objects.all().select_related("user").order_by("user__email", "name")
            if options["user"]:
                qs = qs.filter(user__email__iexact=options["user"]) | qs.filter(
                    user__username__iexact=options["user"]
                )
            if options["broker"]:
                qs = qs.filter(broker=options["broker"].upper())

            self.stdout.write(self.style.MIGRATE_HEADING(
                f"{'ID':>4}  {'BROKER':<8} {'MODE':<6} {'ACTIVE':<7} {'NAME':<30} {'USER'}"
            ))
            for acc in qs:
                self.stdout.write(
                    f"{acc.id:>4}  {acc.broker:<8} {acc.mode:<6} "
                    f"{('Y' if acc.is_active else 'N'):<7} "
                    f"{acc.name[:30]:<30} {acc.user.email or acc.user.username}"
                )
            return

        # ── Modification ────────────────────────────────────────────────
        if not options["mode"]:
            raise CommandError("--mode est requis (PAPER ou LIVE) sauf avec --list.")

        if options["account_id"]:
            account = BrokerAccount.objects.filter(pk=options["account_id"]).first()
            if not account:
                raise CommandError(f"BrokerAccount #{options['account_id']} introuvable.")
            self._update_one(account, options["mode"])
            return

        # Filtre user + broker
        qs = BrokerAccount.objects.all()
        if options["user"]:
            qs = qs.filter(user__email__iexact=options["user"]) | qs.filter(
                user__username__iexact=options["user"]
            )
        if options["broker"]:
            qs = qs.filter(broker=options["broker"].upper())

        if not qs.exists():
            raise CommandError("Aucun BrokerAccount ne correspond aux filtres.")

        for acc in qs:
            self._update_one(acc, options["mode"])

    def _update_one(self, account: BrokerAccount, new_mode: str):
        old_mode = account.mode
        if old_mode == new_mode:
            self.stdout.write(self.style.WARNING(
                f"#{account.id} {account.broker}/{account.name} déjà en mode {new_mode}, no-op."
            ))
            return
        account.mode = new_mode
        account.save(update_fields=["mode", "updated_at"]
                     if "updated_at" in [f.name for f in account._meta.fields]
                     else ["mode"])
        self.stdout.write(self.style.SUCCESS(
            f"#{account.id} {account.broker}/{account.name} : "
            f"{old_mode} → {new_mode} ✓"
        ))
