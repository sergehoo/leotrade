"""
market/services_quotes.py
=========================

Cotation d'un instrument, avec son âge.

`Asset` ne porte aucun prix : le dernier cours se déduit de la bougie la
plus récente. Rien n'indiquait jusqu'ici quand cette bougie avait été
enregistrée, et `Asset.market_status` vaut « OPEN » par défaut sans que
personne ne le mette à jour.

Sur la base de développement, les 46 instruments affichent « OPEN » alors
que leur dernière bougie date de cinq mois. Présenter ce chiffre comme un
cours courant est précisément ce que la règle « ne jamais inventer un
cours » interdit : un prix périmé présenté comme actuel est plus
dangereux qu'une absence de prix, parce qu'il se décide dessus.

Chaque cotation sort donc accompagnée de sa date, de son âge et d'une
classe de fraîcheur. Les seuils sont relatifs à l'unité de temps : une
bougie journalière vieille de deux jours est normale, une bougie d'une
minute vieille de deux jours ne l'est pas.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.utils import timezone

log = logging.getLogger("leotrade.market.quotes")

ZERO = Decimal("0")

#: Au-delà de ce multiple de l'unité de temps, la cotation n'est plus
#: présentée comme courante.
LIVE_FACTOR = 2
DELAYED_FACTOR = 12


class Freshness:
    LIVE = "LIVE"
    DELAYED = "DELAYED"
    STALE = "STALE"
    NO_DATA = "NO_DATA"


FRESHNESS_LABELS = {
    Freshness.LIVE: "À jour",
    Freshness.DELAYED: "Différé",
    Freshness.STALE: "Périmé",
    Freshness.NO_DATA: "Aucune donnée",
}


def _money(value, precision: int = 8) -> str | None:
    """Montant en chaîne, sans notation exponentielle.

    `Decimal.normalize()` rend « 1E+2 » pour 100.00 : le client afficherait
    cela tel quel. On formate donc en virgule fixe, puis on retire les
    zéros de fin à la main.
    """
    if value is None:
        return None
    quantum = Decimal(1).scaleb(-precision)
    text = format(Decimal(value).quantize(quantum), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def classify_freshness(age_seconds: float | None, timeframe_minutes: int) -> str:
    """Classe une cotation d'après son âge, relativement à son unité de temps."""
    if age_seconds is None:
        return Freshness.NO_DATA
    window = max(timeframe_minutes, 1) * 60
    if age_seconds <= window * LIVE_FACTOR:
        return Freshness.LIVE
    if age_seconds <= window * DELAYED_FACTOR:
        return Freshness.DELAYED
    return Freshness.STALE


class MarketQuoteService:

    DEFAULT_TIMEFRAME = "1d"

    @staticmethod
    def _timeframe(code: str | None):
        from market.models import Timeframe

        wanted = code or MarketQuoteService.DEFAULT_TIMEFRAME
        timeframe = Timeframe.objects.filter(code=wanted).first()
        if timeframe is None:
            timeframe = Timeframe.objects.order_by("minutes").first()
        return timeframe

    @classmethod
    def quote(cls, asset, timeframe_code: str | None = None) -> dict:
        """Dernier cours connu d'un instrument, daté et qualifié."""
        from market.models import Candle

        timeframe = cls._timeframe(timeframe_code)
        if timeframe is None:
            return cls._empty(asset, None)

        candles = list(
            Candle.objects
            .filter(asset=asset, timeframe=timeframe)
            .order_by("-open_time")
            .values("close", "open", "high", "low", "volume", "close_time")[:2]
        )
        if not candles:
            return cls._empty(asset, timeframe)

        latest = candles[0]
        previous = candles[1] if len(candles) > 1 else None

        price = Decimal(latest["close"])
        reference = Decimal(previous["close"]) if previous else Decimal(latest["open"])

        change = price - reference
        change_percent = (
            (change / reference * Decimal("100")) if reference else ZERO
        )

        as_of = latest["close_time"]
        age = (timezone.now() - as_of).total_seconds() if as_of else None
        freshness = classify_freshness(age, timeframe.minutes)

        return {
            "asset_id": asset.pk,
            "symbol": asset.symbol,
            "name": asset.name or asset.symbol,
            "asset_class": asset.asset_class,
            # Source explicite : l'utilisateur doit pouvoir savoir d'où
            # vient le chiffre avant de s'en servir.
            "source": asset.exchange,
            "timeframe": timeframe.code,

            "price": _money(price, asset.price_precision or 8),
            "open": _money(latest["open"], asset.price_precision or 8),
            "high": _money(latest["high"], asset.price_precision or 8),
            "low": _money(latest["low"], asset.price_precision or 8),
            "volume": _money(latest["volume"], 8),

            "change": _money(change, asset.price_precision or 8),
            "change_percent": str(change_percent.quantize(Decimal("0.01"))),

            "as_of": as_of,
            "age_seconds": int(age) if age is not None else None,
            "freshness": freshness,
            "freshness_label": FRESHNESS_LABELS[freshness],
            # Statut DÉCLARÉ sur l'instrument. Il est conservé tel quel mais
            # nommé pour ce qu'il est : personne ne le met à jour, et il
            # vaut « OPEN » sur des instruments dont la donnée a des mois.
            "declared_market_status": asset.market_status,
            "is_tradable_quote": freshness == Freshness.LIVE,
        }

    @staticmethod
    def _empty(asset, timeframe) -> dict:
        """Aucune donnée : on le dit, on n'invente pas un zéro."""
        return {
            "asset_id": asset.pk,
            "symbol": asset.symbol,
            "name": asset.name or asset.symbol,
            "asset_class": asset.asset_class,
            "source": asset.exchange,
            "timeframe": getattr(timeframe, "code", None),
            "price": None,
            "open": None,
            "high": None,
            "low": None,
            "volume": None,
            "change": None,
            "change_percent": None,
            "as_of": None,
            "age_seconds": None,
            "freshness": Freshness.NO_DATA,
            "freshness_label": FRESHNESS_LABELS[Freshness.NO_DATA],
            "declared_market_status": asset.market_status,
            "is_tradable_quote": False,
        }

    @classmethod
    def quotes_for(cls, assets, timeframe_code: str | None = None) -> list[dict]:
        return [cls.quote(asset, timeframe_code) for asset in assets]

    @classmethod
    def history(cls, asset, timeframe_code: str | None = None, limit: int = 200) -> dict:
        """Historique de bougies, avec la fraîcheur de la série."""
        from market.models import Candle

        timeframe = cls._timeframe(timeframe_code)
        if timeframe is None:
            return {"timeframe": None, "candles": [], "freshness": Freshness.NO_DATA}

        limit = max(1, min(int(limit or 200), 1000))
        rows = list(
            Candle.objects
            .filter(asset=asset, timeframe=timeframe)
            .order_by("-open_time")
            .values("open_time", "close_time", "open", "high", "low", "close", "volume")[:limit]
        )
        rows.reverse()

        precision = asset.price_precision or 8
        as_of = rows[-1]["close_time"] if rows else None
        age = (timezone.now() - as_of).total_seconds() if as_of else None
        freshness = classify_freshness(age, timeframe.minutes)

        return {
            "asset_id": asset.pk,
            "symbol": asset.symbol,
            "source": asset.exchange,
            "timeframe": timeframe.code,
            "as_of": as_of,
            "age_seconds": int(age) if age is not None else None,
            "freshness": freshness,
            "freshness_label": FRESHNESS_LABELS[freshness],
            "candles": [
                {
                    "open_time": row["open_time"],
                    "open": _money(row["open"], precision),
                    "high": _money(row["high"], precision),
                    "low": _money(row["low"], precision),
                    "close": _money(row["close"], precision),
                    "volume": _money(row["volume"], 8),
                }
                for row in rows
            ],
        }
