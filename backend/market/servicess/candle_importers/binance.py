from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from django.db import transaction

from brokers.services.binance import BinanceClient
from market.models import Asset, Candle, Timeframe


BINANCE_INTERVAL_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
    "1w": "1w",
    "1M": "1M",
}


class BinanceCandleImporter:
    @staticmethod
    def _to_dt(ms: int) -> datetime:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)

    @classmethod
    @transaction.atomic
    def import_klines(cls, asset: Asset, timeframe: Timeframe, limit: int = 500) -> dict:
        if asset.exchange != "BINANCE":
            raise ValueError(f"L'asset {asset.symbol} n'est pas de type BINANCE.")

        interval = BINANCE_INTERVAL_MAP.get(timeframe.code)
        if not interval:
            raise ValueError(f"Timeframe non supporté pour Binance: {timeframe.code}")

        client = BinanceClient(api_key="", api_secret="")
        rows = client.klines(symbol=asset.symbol, interval=interval, limit=limit)

        created = 0
        updated = 0

        for row in rows:
            open_time = cls._to_dt(int(row[0]))
            close_time = cls._to_dt(int(row[6]))

            defaults = {
                "close_time": close_time,
                "open": Decimal(str(row[1])),
                "high": Decimal(str(row[2])),
                "low": Decimal(str(row[3])),
                "close": Decimal(str(row[4])),
                "volume": Decimal(str(row[5])),
                "trade_count": int(row[8] or 0),
            }

            obj, was_created = Candle.objects.update_or_create(
                asset=asset,
                timeframe=timeframe,
                open_time=open_time,
                defaults=defaults,
            )

            if was_created:
                created += 1
            else:
                updated += 1

        return {
            "asset": asset.symbol,
            "timeframe": timeframe.code,
            "rows": len(rows),
            "created": created,
            "updated": updated,
        }