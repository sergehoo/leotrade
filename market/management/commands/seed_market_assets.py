from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from market.models import Asset, Timeframe


class Command(BaseCommand):
    help = "Peuple automatiquement les assets multi-marchés : Binance, MT5, Deriv."

    CRYPTO_BINANCE = [
        ("BTCUSDT", "BTC", "USDT"),
        ("ETHUSDT", "ETH", "USDT"),
        ("BNBUSDT", "BNB", "USDT"),
        ("SOLUSDT", "SOL", "USDT"),
        ("XRPUSDT", "XRP", "USDT"),
        ("ADAUSDT", "ADA", "USDT"),
        ("DOGEUSDT", "DOGE", "USDT"),
        ("AVAXUSDT", "AVAX", "USDT"),
        ("DOTUSDT", "DOT", "USDT"),
        ("LINKUSDT", "LINK", "USDT"),
        ("MATICUSDT", "MATIC", "USDT"),
        ("LTCUSDT", "LTC", "USDT"),
    ]

    FOREX_MT5 = [
        ("EURUSD", "EUR", "USD"),
        ("GBPUSD", "GBP", "USD"),
        ("USDJPY", "USD", "JPY"),
        ("USDCHF", "USD", "CHF"),
        ("AUDUSD", "AUD", "USD"),
        ("USDCAD", "USD", "CAD"),
        ("NZDUSD", "NZD", "USD"),
        ("EURGBP", "EUR", "GBP"),
        ("EURJPY", "EUR", "JPY"),
        ("GBPJPY", "GBP", "JPY"),
        ("XAUUSD", "XAU", "USD"),
        ("XAGUSD", "XAG", "USD"),
    ]

    DERIV_SYNTHETIC = [
        # ─────────────────────────────
        # Volatility Indices (classiques)
        # ─────────────────────────────
        ("R_10", None, None),
        ("R_25", None, None),
        ("R_50", None, None),
        ("R_75", None, None),
        ("R_100", None, None),

        # ─────────────────────────────
        # Volatility Indices (1s)
        # ─────────────────────────────
        ("1HZ10V", None, None),
        ("1HZ25V", None, None),
        ("1HZ50V", None, None),
        ("1HZ75V", None, None),
        ("1HZ100V", None, None),

        # ─────────────────────────────
        # Boom & Crash
        # ─────────────────────────────
        ("BOOM1000", None, None),
        ("BOOM500", None, None),
        ("CRASH1000", None, None),
        ("CRASH500", None, None),

        # ─────────────────────────────
        # Jump Indices
        # ─────────────────────────────
        ("JD10", None, None),
        ("JD25", None, None),
        ("JD50", None, None),
        ("JD75", None, None),
        ("JD100", None, None),

        # ─────────────────────────────
        # Step Indices
        # ─────────────────────────────
        ("STEPINDEX", None, None),

        # ─────────────────────────────
        # Range Break Indices
        # ─────────────────────────────
        ("RDBULL", None, None),
        ("RDBEAR", None, None),
    ]

    TIMEFRAMES = [
        ("5m", "5 minutes", 5),
        ("15m", "15 minutes", 15),
        ("30m", "30 minutes", 30),
        ("1h", "1 heure", 60),
        ("4h", "4 heures", 240),
        ("1d", "1 jour", 1440),
        ("1w", "1 semaine", 10080),
        ("1M", "1 mois", 43200),
    ]

    def create_or_update_asset(
        self,
        *,
        symbol: str,
        asset_class: str,
        exchange: str,
        base_asset: str | None = None,
        quote_asset: str | None = None,
        is_active: bool = True,
    ):
        obj, created = Asset.objects.update_or_create(
            symbol=symbol,
            defaults={
                "base_asset": base_asset,
                "quote_asset": quote_asset,
                "asset_class": asset_class,
                "exchange": exchange,
                "is_active": is_active,
            },
        )
        return obj, created

    @transaction.atomic
    def handle(self, *args, **options):
        created_assets = 0
        updated_assets = 0
        created_timeframes = 0

        self.stdout.write(self.style.NOTICE("Création / vérification des timeframes..."))
        for code, label, minutes in self.TIMEFRAMES:
            _, created = Timeframe.objects.get_or_create(
                code=code,
                defaults={"label": label, "minutes": minutes},
            )
            if created:
                created_timeframes += 1

        self.stdout.write(self.style.NOTICE("Peuplement des assets Binance / Crypto..."))
        for symbol, base_asset, quote_asset in self.CRYPTO_BINANCE:
            _, created = self.create_or_update_asset(
                symbol=symbol,
                asset_class="CRYPTO",
                exchange="BINANCE",
                base_asset=base_asset,
                quote_asset=quote_asset,
            )
            if created:
                created_assets += 1
            else:
                updated_assets += 1

        self.stdout.write(self.style.NOTICE("Peuplement des assets MT5 / Forex..."))
        for symbol, base_asset, quote_asset in self.FOREX_MT5:
            asset_class = "FOREX"
            if symbol in ["XAUUSD", "XAGUSD"]:
                asset_class = "COMMODITY"

            _, created = self.create_or_update_asset(
                symbol=symbol,
                asset_class=asset_class,
                exchange="MT5",
                base_asset=base_asset,
                quote_asset=quote_asset,
            )
            if created:
                created_assets += 1
            else:
                updated_assets += 1

        self.stdout.write(self.style.NOTICE("Peuplement des assets Deriv / Indices synthétiques..."))
        for symbol, base_asset, quote_asset in self.DERIV_SYNTHETIC:
            _, created = self.create_or_update_asset(
                symbol=symbol,
                asset_class="INDEX",
                exchange="DERIV",
                base_asset=base_asset,
                quote_asset=quote_asset,
            )
            if created:
                created_assets += 1
            else:
                updated_assets += 1

        self.stdout.write(self.style.SUCCESS("Peuplement terminé."))
        self.stdout.write(f"Timeframes créés : {created_timeframes}")
        self.stdout.write(f"Assets créés     : {created_assets}")
        self.stdout.write(f"Assets mis à jour: {updated_assets}")