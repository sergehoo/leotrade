from django.core.management.base import BaseCommand, CommandError

from brokers.models import BrokerAccount
from brokers.services.deriv import DerivClient


class Command(BaseCommand):
    help = "Teste la connexion Deriv moderne (REST + OTP + WebSocket)"

    def add_arguments(self, parser):
        parser.add_argument("--broker-id", type=int, required=True, help="ID du BrokerAccount Deriv")

    def handle(self, *args, **options):
        broker_id = options["broker_id"]

        broker = BrokerAccount.objects.filter(pk=broker_id).first()
        if not broker:
            raise CommandError(f"Aucun BrokerAccount avec id={broker_id}")

        if broker.broker != "DERIV":
            raise CommandError(f"Le compte id={broker_id} n'est pas de type DERIV mais {broker.broker}")

        client = DerivClient(
            token=broker.deriv_token,
            app_id=broker.deriv_app_id,
        )

        try:
            self.stdout.write(self.style.NOTICE("Lecture des comptes options Deriv via REST..."))
            accounts_resp = client.list_options_accounts()

            accounts = accounts_resp.get("data", [])
            if not accounts:
                raise CommandError("Aucun compte options Deriv retourné par l'API.")

            preferred_type = (broker.deriv_account_type or "").lower()
            selected = None

            if preferred_type:
                for acc in accounts:
                    if str(acc.get("account_type", "")).lower() == preferred_type:
                        selected = acc
                        break

            if not selected:
                selected = accounts[0]

            account_id = selected.get("account_id")
            if not account_id:
                raise CommandError(f"Compte options invalide: {selected}")

            self.stdout.write(self.style.SUCCESS(f"Compte sélectionné: {account_id} ({selected.get('account_type')})"))

            self.stdout.write(self.style.NOTICE("Demande OTP WebSocket..."))
            ws_url = client.get_otp_ws_url(account_id)
            self.stdout.write(self.style.SUCCESS(f"OTP URL reçue: {ws_url}"))

            self.stdout.write(self.style.NOTICE("Connexion WebSocket OTP..."))
            client.connect_with_otp_url(ws_url)

            self.stdout.write(self.style.NOTICE("Ping..."))
            ping = client.ping()

            self.stdout.write(self.style.NOTICE("Balance WebSocket..."))
            balance = client.balance_ws()

            self.stdout.write(self.style.NOTICE("Portfolio WebSocket..."))
            portfolio = client.portfolio_ws()

            self.stdout.write(self.style.SUCCESS("Connexion Deriv réussie."))
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Ping:"))
            self.stdout.write(str(ping))
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Balance:"))
            self.stdout.write(str(balance))
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Portfolio:"))
            self.stdout.write(str(portfolio))

        except Exception as exc:
            raise CommandError(f"Test Deriv échoué: {exc}")
        finally:
            client.close()