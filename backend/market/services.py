# /Users/ogahserge/Documents/leoTrade/market/services.py

from datetime import datetime, timezone as dt_timezone
from decimal import Decimal, InvalidOperation

import pandas as pd
from django.db import transaction

from brokers.services.binance import BinanceClient
from .models import Asset, Timeframe, Candle, MarketFeature
from .indicators import compute_indicators


def _to_decimal(value, default="0"):
    try:
        if value is None:
            return Decimal(default)
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


@transaction.atomic
def import_binance_klines(asset: Asset, timeframe: Timeframe, limit: int = 500):
    """
    Importe les bougies Binance pour un asset/timeframe donné.
    Retourne le nombre de lignes créées.
    """
    client = BinanceClient()
    rows = client.klines(symbol=asset.symbol, interval=timeframe.code, limit=limit)

    created = 0

    for row in rows:
        open_time = datetime.fromtimestamp(row[0] / 1000, tz=dt_timezone.utc)
        close_time = datetime.fromtimestamp(row[6] / 1000, tz=dt_timezone.utc)

        _, inserted = Candle.objects.update_or_create(
            asset=asset,
            timeframe=timeframe,
            open_time=open_time,
            defaults={
                "close_time": close_time,
                "open": _to_decimal(row[1]),
                "high": _to_decimal(row[2]),
                "low": _to_decimal(row[3]),
                "close": _to_decimal(row[4]),
                "volume": _to_decimal(row[5]),
                "trade_count": int(row[8] or 0),
            },
        )

        if inserted:
            created += 1

    return created


def get_asset_candles(asset: Asset, timeframe: Timeframe, limit: int = 300):
    """
    Récupère les dernières candles d’un asset pour un timeframe précis.
    Toujours filtrer avec timeframe pour éviter les mélanges de granularité.
    """
    return (
        Candle.objects
        .filter(asset=asset, timeframe=timeframe)
        .order_by("open_time")[:limit]
    )


@transaction.atomic
def compute_market_features(asset: Asset, timeframe: Timeframe):
    """
    Calcule et enregistre les features techniques pour un asset/timeframe.
    """
    qs = (
        Candle.objects
        .filter(asset=asset, timeframe=timeframe)
        .order_by("open_time")
        .values("open_time", "open", "high", "low", "close", "volume")
    )

    df = pd.DataFrame(list(qs))
    if df.empty:
        return 0

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["open_time", "open", "high", "low", "close"])
    if df.empty:
        return 0

    df = compute_indicators(df)

    count = 0
    for _, row in df.iterrows():
        if pd.isna(row.get("open_time")):
            continue

        _, _ = MarketFeature.objects.update_or_create(
            asset=asset,
            timeframe=timeframe,
            candle_time=row["open_time"],
            defaults={
                "rsi_14": None if pd.isna(row.get("rsi_14")) else float(row["rsi_14"]),
                "macd": None if pd.isna(row.get("macd")) else float(row["macd"]),
                "macd_signal": None if pd.isna(row.get("macd_signal")) else float(row["macd_signal"]),
                "sma_20": None if pd.isna(row.get("sma_20")) else float(row["sma_20"]),
                "sma_50": None if pd.isna(row.get("sma_50")) else float(row["sma_50"]),
                "atr_14": None if pd.isna(row.get("atr_14")) else float(row["atr_14"]),
                "bb_high": None if pd.isna(row.get("bb_high")) else float(row["bb_high"]),
                "bb_low": None if pd.isna(row.get("bb_low")) else float(row["bb_low"]),
                "returns_1": None if pd.isna(row.get("returns_1")) else float(row["returns_1"]),
                "returns_5": None if pd.isna(row.get("returns_5")) else float(row["returns_5"]),
                "volatility_20": None if pd.isna(row.get("volatility_20")) else float(row["volatility_20"]),
            },
        )
        count += 1

    return count