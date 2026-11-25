# strategies/management/commands/run_strategies.py
from django.core.management.base import BaseCommand

from strategies.services.strategy_runner import StrategyRunnerService


class Command(BaseCommand):
    help = "Exécute toutes les stratégies autonomes actives"

    def add_arguments(self, parser):
        parser.add_argument(
            "--fail-fast",
            action="store_true",
            help="Stoppe immédiatement à la première erreur critique.",
        )
        parser.add_argument(
            "--verbose-runs",
            action="store_true",
            help="Affiche le détail de chaque run.",
        )

    def handle(self, *args, **options):
        fail_fast = options["fail_fast"]
        verbose_runs = options["verbose_runs"]

        self.stdout.write(self.style.NOTICE("Lancement des stratégies autonomes..."))

        try:
            runs = StrategyRunnerService.run_all_autonomous()
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"Erreur globale d'exécution: {exc}"))
            if fail_fast:
                raise
            return

        success_count = 0
        failed_count = 0
        skipped_count = 0

        for run in runs:
            if run.status == "SUCCEEDED":
                success_count += 1
                level = self.style.SUCCESS
            elif run.status == "SKIPPED":
                skipped_count += 1
                level = self.style.WARNING
            else:
                failed_count += 1
                level = self.style.ERROR

            if verbose_runs:
                self.stdout.write(
                    level(
                        f"[{run.status}] "
                        f"strategy={run.strategy.name} "
                        f"runtime={run.runtime_ms}ms "
                        f"started={run.run_started_at} "
                        f"error={run.error_message or '-'}"
                    )
                )

        self.stdout.write("")
        self.stdout.write(self.style.NOTICE("Résumé d'exécution"))
        self.stdout.write(self.style.SUCCESS(f"Succès : {success_count}"))
        self.stdout.write(self.style.WARNING(f"Skipped : {skipped_count}"))
        self.stdout.write(self.style.ERROR(f"Échecs : {failed_count}"))
        self.stdout.write(self.style.SUCCESS("Terminé."))