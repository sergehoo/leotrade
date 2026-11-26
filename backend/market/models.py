from django.db import models

# Create your models here.
from django.db import models
from core.models import TimeStampedModel

class Asset(TimeStampedModel):
    ASSET_CLASS_CHOICES = [
        ("CRYPTO", "Crypto"),
        ("FOREX", "Forex"),
        ("STOCK", "Stock"),
        ("INDEX", "Index"),
        ("COMMODITY", "Commodity"),
    ]
    name = models.CharField(max_length=100, blank=True, null=True)
    symbol = models.CharField(max_length=30, unique=True, db_index=True)
    base_asset = models.CharField(max_length=20, blank=True, null=True)
    quote_asset = models.CharField(max_length=20, blank=True, null=True)
    asset_class = models.CharField(max_length=20, choices=ASSET_CLASS_CHOICES, db_index=True)
    exchange = models.CharField(max_length=50, default="BINANCE", db_index=True)
    tick_size = models.DecimalField(max_digits=20, decimal_places=10, null=True, blank=True)
    lot_step = models.DecimalField(max_digits=20, decimal_places=10, null=True, blank=True)
    price_precision = models.PositiveIntegerField(default=2)
    quantity_precision = models.PositiveIntegerField(default=4)
    market_status = models.CharField(max_length=20, default="OPEN", db_index=True)
    icon = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.symbol


class Timeframe(TimeStampedModel):
    code = models.CharField(max_length=10, unique=True)   # 1m, 5m, 1h, 1d
    label = models.CharField(max_length=50)
    minutes = models.PositiveIntegerField()

    def __str__(self):
        return self.code


class Candle(TimeStampedModel):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="candles")
    timeframe = models.ForeignKey(Timeframe, on_delete=models.CASCADE)
    open_time = models.DateTimeField(db_index=True)
    close_time = models.DateTimeField(db_index=True)

    open = models.DecimalField(max_digits=24, decimal_places=10)
    high = models.DecimalField(max_digits=24, decimal_places=10)
    low = models.DecimalField(max_digits=24, decimal_places=10)
    close = models.DecimalField(max_digits=24, decimal_places=10)
    volume = models.DecimalField(max_digits=30, decimal_places=10, default=0)

    trade_count = models.PositiveBigIntegerField(default=0)

    class Meta:
        unique_together = [("asset", "timeframe", "open_time")]
        indexes = [
            models.Index(fields=["asset", "timeframe", "open_time"]),
            models.Index(fields=["asset", "open_time"]),
        ]
        ordering = ["-open_time"]

    def __str__(self):
        return f"{self.asset.symbol} {self.timeframe.code} {self.open_time}"


class MarketFeature(TimeStampedModel):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="features")
    timeframe = models.ForeignKey(Timeframe, on_delete=models.CASCADE)
    candle_time = models.DateTimeField(db_index=True)

    rsi_14 = models.FloatField(blank=True, null=True)
    macd = models.FloatField(blank=True, null=True)
    macd_signal = models.FloatField(blank=True, null=True)
    sma_20 = models.FloatField(blank=True, null=True)
    sma_50 = models.FloatField(blank=True, null=True)
    atr_14 = models.FloatField(blank=True, null=True)
    bb_high = models.FloatField(blank=True, null=True)
    bb_low = models.FloatField(blank=True, null=True)
    returns_1 = models.FloatField(blank=True, null=True)
    returns_5 = models.FloatField(blank=True, null=True)
    volatility_20 = models.FloatField(blank=True, null=True)

    class Meta:
        unique_together = [("asset", "timeframe", "candle_time")]
        indexes = [
            models.Index(fields=["asset", "timeframe", "candle_time"]),
        ]

    def __str__(self):
        return f"{self.asset.symbol} {self.timeframe.code} {self.candle_time}"



# Import explicite : sans lui, Django ne découvre pas le modèle au
# chargement de l'app et `makemigrations` proposerait de le supprimer.
from market.models_watchlist import WatchlistItem  # noqa: E402,F401
