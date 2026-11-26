"""
api/serializers/market.py
=========================

Contrat d'API des marchés.

Une cotation ne sort jamais seule : elle est toujours accompagnée de sa
date, de son âge et d'une classe de fraîcheur. Un prix sans date est un
prix qu'on croit courant, et c'est sur cette croyance qu'on prend une
décision — le mode le plus sûr de perdre de l'argent sur une donnée
vieille de plusieurs mois.
"""

from __future__ import annotations

from rest_framework import serializers

from market.models import Asset
from market.models_watchlist import WatchlistItem


class AssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Asset
        fields = [
            "id", "symbol", "name", "asset_class", "exchange",
            "base_asset", "quote_asset",
            "price_precision", "quantity_precision",
            "tick_size", "lot_step",
            "market_status", "is_active", "icon",
        ]
        read_only_fields = fields


class QuoteSerializer(serializers.Serializer):
    """Dernier cours connu — jamais présenté comme forcément courant."""

    asset_id = serializers.IntegerField()
    symbol = serializers.CharField()
    name = serializers.CharField()
    asset_class = serializers.CharField()
    #: Place d'où vient le chiffre.
    source = serializers.CharField()
    timeframe = serializers.CharField(allow_null=True)

    # Montants en chaîne : le backend calcule en Decimal, et les clients
    # n'ont pas d'équivalent natif.
    price = serializers.CharField(allow_null=True)
    open = serializers.CharField(allow_null=True)
    high = serializers.CharField(allow_null=True)
    low = serializers.CharField(allow_null=True)
    volume = serializers.CharField(allow_null=True)
    change = serializers.CharField(allow_null=True)
    change_percent = serializers.CharField(allow_null=True)

    #: Horodatage de la bougie dont le prix est tiré.
    as_of = serializers.DateTimeField(allow_null=True)
    age_seconds = serializers.IntegerField(allow_null=True)
    #: LIVE | DELAYED | STALE | NO_DATA, relatif à l'unité de temps.
    freshness = serializers.CharField()
    freshness_label = serializers.CharField()
    #: Statut porté par l'instrument. Nommé « déclaré » parce que rien ne
    #: le met à jour : il vaut « OPEN » sur des instruments dont la donnée
    #: a plusieurs mois.
    declared_market_status = serializers.CharField()
    #: Faux dès que la cotation n'est plus à jour : une décision ne doit
    #: pas se prendre sur un prix périmé.
    is_tradable_quote = serializers.BooleanField()


class CandleSerializer(serializers.Serializer):
    open_time = serializers.DateTimeField()
    open = serializers.CharField(allow_null=True)
    high = serializers.CharField(allow_null=True)
    low = serializers.CharField(allow_null=True)
    close = serializers.CharField(allow_null=True)
    volume = serializers.CharField(allow_null=True)


class CandleHistorySerializer(serializers.Serializer):
    asset_id = serializers.IntegerField()
    symbol = serializers.CharField()
    source = serializers.CharField()
    timeframe = serializers.CharField(allow_null=True)
    as_of = serializers.DateTimeField(allow_null=True)
    age_seconds = serializers.IntegerField(allow_null=True)
    freshness = serializers.CharField()
    freshness_label = serializers.CharField()
    candles = CandleSerializer(many=True)


class WatchlistItemSerializer(serializers.ModelSerializer):
    # Un instrument n'appartient à personne : `OwnedRelatedField` serait
    # le mauvais outil ici. La seule restriction utile est de ne pas
    # laisser suivre un symbole retiré.
    asset = serializers.PrimaryKeyRelatedField(
        queryset=Asset.objects.filter(is_active=True),
    )
    symbol = serializers.CharField(source="asset.symbol", read_only=True)
    asset_class = serializers.CharField(source="asset.asset_class", read_only=True)
    exchange = serializers.CharField(source="asset.exchange", read_only=True)

    class Meta:
        model = WatchlistItem
        fields = [
            "id", "asset", "symbol", "asset_class", "exchange",
            "position", "note", "created_at",
        ]
        read_only_fields = ["id", "symbol", "asset_class", "exchange", "created_at"]
