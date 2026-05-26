from django.core.management.base import BaseCommand, CommandError
from market.models import Asset, Timeframe
from market.services import compute_market_features


class Command(BaseCommand):
    help = "Calcule et stocke les features techniques à partir des bougies"

    def add_arguments(self, parser):
        parser.add_argument("--symbol", required=True)
        parser.add_argument("--timeframe", required=True)

    def handle(self, *args, **options):
        symbol = options["symbol"].upper()
        timeframe_code = options["timeframe"]
        try:
            asset = Asset.objects.get(symbol=symbol)
            timeframe = Timeframe.objects.get(code=timeframe_code)
        except Asset.DoesNotExist as exc:
            raise CommandError(f"Asset introuvable: {symbol}") from exc
        except Timeframe.DoesNotExist as exc:
            raise CommandError(f"Timeframe introuvable: {timeframe_code}") from exc

        count = compute_market_features(asset=asset, timeframe=timeframe)
        self.stdout.write(self.style.SUCCESS(f"{count} lignes de features calculées"))