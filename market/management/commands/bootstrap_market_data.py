from django.core.management.base import BaseCommand

from market.models import Asset, Timeframe
from market.servicess.candle_importers.binance import BinanceCandleImporter
from market.servicess.candle_importers.deriv import DerivCandleImporter
from market.servicess.features import FeatureComputationService


class Command(BaseCommand):
    help = "Initialise les timeframes, importe les candles et calcule les features."

    def handle(self, *args, **options):
        required_timeframes = [
            ("5m", "5 minutes", 5),
            ("15m", "15 minutes", 15),
            ("30m", "30 minutes", 30),
            ("1h", "1 heure", 60),
            ("4h", "4 heures", 240),
            ("1d", "1 jour", 1440),
            ("1w", "1 semaine", 10080),
            ("1M", "1 mois", 43200),
        ]

        for code, label, minutes in required_timeframes:
            Timeframe.objects.get_or_create(
                code=code,
                defaults={"label": label, "minutes": minutes},
            )

        self.stdout.write(self.style.SUCCESS("Timeframes vérifiés."))

        binance_assets = Asset.objects.filter(exchange="BINANCE", is_active=True)
        deriv_assets = Asset.objects.filter(exchange="DERIV", is_active=True)

        # Binance supporte bien les timeframes longs
        binance_timeframes = Timeframe.objects.filter(
            code__in=["5m", "15m", "1h", "4h", "1d", "1w", "1M"]
        ).order_by("minutes")

        # Deriv: rester prudent, éviter 1w / 1M dans ce pipeline
        deriv_timeframes = Timeframe.objects.filter(
            code__in=["5m", "15m", "1h", "4h", "1d"]
        ).order_by("minutes")

        # Calcul des features sur l’ensemble disponible
        feature_timeframes = Timeframe.objects.filter(
            code__in=["5m", "15m", "1h", "4h", "1d", "1w", "1M"]
        ).order_by("minutes")

        # ─────────────────────────────────────────────
        # Import Binance
        # ─────────────────────────────────────────────
        for asset in binance_assets:
            for timeframe in binance_timeframes:
                try:
                    result = BinanceCandleImporter.import_klines(
                        asset=asset,
                        timeframe=timeframe,
                        limit=500,
                    )
                    self.stdout.write(f"[BINANCE] {result}")
                except Exception as exc:
                    self.stdout.write(
                        self.style.ERROR(
                            f"[BINANCE][ERROR] asset={asset.symbol} tf={timeframe.code} -> {exc}"
                        )
                    )

        # ─────────────────────────────────────────────
        # Import Deriv
        # ─────────────────────────────────────────────
        for asset in deriv_assets:
            for timeframe in deriv_timeframes:
                try:
                    result = DerivCandleImporter.import_candles(
                        asset=asset,
                        timeframe=timeframe,
                        count=300,
                    )
                    self.stdout.write(f"[DERIV] {result}")
                except Exception as exc:
                    self.stdout.write(
                        self.style.ERROR(
                            f"[DERIV][ERROR] asset={asset.symbol} tf={timeframe.code} -> {exc}"
                        )
                    )

        # ─────────────────────────────────────────────
        # Calcul des features
        # ─────────────────────────────────────────────
        for asset in Asset.objects.filter(is_active=True):
            for timeframe in feature_timeframes:
                try:
                    result = FeatureComputationService.compute_for_asset_timeframe(
                        asset=asset,
                        timeframe=timeframe,
                        lookback=500,
                    )
                    self.stdout.write(f"[FEATURES] {result}")
                except Exception as exc:
                    self.stdout.write(
                        self.style.ERROR(
                            f"[FEATURES][ERROR] asset={asset.symbol} tf={timeframe.code} -> {exc}"
                        )
                    )

        self.stdout.write(self.style.SUCCESS("Bootstrap market data terminé."))