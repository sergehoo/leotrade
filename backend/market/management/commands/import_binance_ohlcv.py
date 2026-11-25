from django.core.management.base import BaseCommand, CommandError
from market.models import Asset, Timeframe
from market.services import import_binance_klines


class Command(BaseCommand):
    help = "Importe les bougies OHLCV depuis Binance"

    def add_arguments(self, parser):
        parser.add_argument("--symbol", required=True)
        parser.add_argument("--timeframe", required=True)
        parser.add_argument("--limit", type=int, default=500)

    def handle(self, *args, **options):
        symbol = options["symbol"].upper()
        timeframe_code = options["timeframe"]
        limit = options["limit"]

        try:
            asset = Asset.objects.get(symbol=symbol)
            timeframe = Timeframe.objects.get(code=timeframe_code)
        except Asset.DoesNotExist as exc:
            raise CommandError(f"Asset introuvable: {symbol}") from exc
        except Timeframe.DoesNotExist as exc:
            raise CommandError(f"Timeframe introuvable: {timeframe_code}") from exc

        created = import_binance_klines(asset=asset, timeframe=timeframe, limit=limit)
        self.stdout.write(self.style.SUCCESS(f"{created} bougies importées pour {symbol} {timeframe_code}"))