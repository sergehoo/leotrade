"""
tests_phase/test_api_market.py
==============================

Contrat de l'API marchés.

La propriété qui compte ici n'est pas l'exactitude du prix — il vient
d'un fournisseur — mais le fait qu'il ne soit JAMAIS présenté comme
courant sans l'être. Sur la base de développement, les 46 instruments se
déclarent « OPEN » alors que leur dernière bougie a cinq mois : un prix
sans date est un prix sur lequel on décide à tort.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from market.models import Asset, Candle, Timeframe
from market.models_watchlist import WatchlistItem
from market.services_quotes import Freshness, classify_freshness

User = get_user_model()


@pytest.fixture(autouse=True)
def _reset_throttle_bucket():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="trader", email="trader@leotrade.test", password="StrongPass123!",
    )


@pytest.fixture
def client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def daily(db):
    return Timeframe.objects.create(code="1d", label="1 jour", minutes=1440)


@pytest.fixture
def asset(db):
    return Asset.objects.create(
        symbol="BTCUSDT", name="Bitcoin", asset_class="CRYPTO",
        exchange="BINANCE", price_precision=2, is_active=True,
    )


def _candle(asset, timeframe, *, close, age_days, open_price=None):
    moment = timezone.now() - timedelta(days=age_days)
    return Candle.objects.create(
        asset=asset, timeframe=timeframe,
        open_time=moment - timedelta(days=1), close_time=moment,
        open=Decimal(open_price if open_price is not None else close),
        high=Decimal(close), low=Decimal(close), close=Decimal(close),
        volume=Decimal("1"),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  1. La fraîcheur — la propriété centrale
# ─────────────────────────────────────────────────────────────────────────────

class TestFreshnessClassification:
    """Les seuils sont relatifs à l'unité de temps : une bougie
    journalière vieille de deux jours est normale, une bougie d'une
    minute vieille de deux jours ne l'est pas."""

    def test_a_recent_candle_is_live(self):
        assert classify_freshness(3600, 1440) == Freshness.LIVE

    def test_a_daily_candle_two_days_old_is_still_live(self):
        assert classify_freshness(2 * 86400, 1440) == Freshness.LIVE

    def test_a_one_minute_candle_two_days_old_is_stale(self):
        assert classify_freshness(2 * 86400, 1) == Freshness.STALE

    def test_the_absence_of_data_is_not_a_freshness_level(self):
        assert classify_freshness(None, 1440) == Freshness.NO_DATA

    def test_a_months_old_daily_candle_is_stale(self):
        """Le cas réellement présent en base de développement."""
        assert classify_freshness(150 * 86400, 1440) == Freshness.STALE


@pytest.mark.django_db
class TestQuoteContract:

    def test_a_quote_always_carries_its_date_and_age(self, client, asset, daily):
        _candle(asset, daily, close="100.00", age_days=0)

        body = client.get(
            reverse("api-assets-quote", kwargs={"pk": asset.pk})
        ).json()

        assert body["as_of"] is not None
        assert body["age_seconds"] is not None
        assert body["freshness"] == Freshness.LIVE
        assert body["source"] == "BINANCE"

    def test_a_stale_quote_is_not_presented_as_tradable(self, client, asset, daily):
        """La donnée de développement a cinq mois ; l'interface ne doit
        pas laisser décider dessus."""
        _candle(asset, daily, close="100.00", age_days=150)

        body = client.get(
            reverse("api-assets-quote", kwargs={"pk": asset.pk})
        ).json()

        assert body["freshness"] == Freshness.STALE
        assert body["is_tradable_quote"] is False
        assert body["price"] is not None, "Le prix reste lisible, mais daté."

    def test_an_asset_without_data_reports_null_not_zero(self, client, asset, daily):
        """Un zéro serait un prix. L'absence de prix doit se dire."""
        body = client.get(
            reverse("api-assets-quote", kwargs={"pk": asset.pk})
        ).json()

        assert body["price"] is None
        assert body["change_percent"] is None
        assert body["freshness"] == Freshness.NO_DATA
        assert body["is_tradable_quote"] is False

    def test_the_declared_status_is_named_for_what_it_is(self, client, asset, daily):
        """`market_status` vaut « OPEN » par défaut et personne ne le met à
        jour : le contrat le nomme « déclaré » pour qu'on ne le confonde
        pas avec un état vérifié."""
        _candle(asset, daily, close="100.00", age_days=150)

        body = client.get(
            reverse("api-assets-quote", kwargs={"pk": asset.pk})
        ).json()

        assert body["declared_market_status"] == "OPEN"
        assert body["freshness"] == Freshness.STALE
        assert "market_status" not in body, (
            "Le champ brut ne doit pas coexister avec sa version qualifiée."
        )

    def test_the_variation_is_computed_against_the_previous_candle(
        self, client, asset, daily,
    ):
        _candle(asset, daily, close="100.00", age_days=2)
        _candle(asset, daily, close="110.00", age_days=1)

        body = client.get(
            reverse("api-assets-quote", kwargs={"pk": asset.pk})
        ).json()

        assert body["price"] == "110"
        assert body["change"] == "10"
        assert body["change_percent"] == "10.00"

    def test_amounts_travel_as_strings(self, client, asset, daily):
        _candle(asset, daily, close="0.00000123", age_days=0)

        body = client.get(
            reverse("api-assets-quote", kwargs={"pk": asset.pk})
        ).json()

        assert isinstance(body["price"], str)

    def test_a_price_is_never_rendered_in_scientific_notation(
        self, client, asset, daily,
    ):
        """Régression : `Decimal.normalize()` rendait « 1E+2 » pour 100.00.
        Le client affichait cette chaîne telle quelle."""
        _candle(asset, daily, close="100.00", age_days=0)

        body = client.get(
            reverse("api-assets-quote", kwargs={"pk": asset.pk})
        ).json()

        assert "E" not in body["price"].upper()
        assert body["price"] == "100"


# ─────────────────────────────────────────────────────────────────────────────
#  2. Catalogue et historique
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestCatalogue:

    def test_retired_instruments_leave_the_default_listing(self, client, asset):
        Asset.objects.create(
            symbol="OLDCOIN", asset_class="CRYPTO", exchange="BINANCE", is_active=False,
        )

        body = client.get(reverse("api-assets-list")).json()
        symbols = {row["symbol"] for row in body["results"]}

        assert "BTCUSDT" in symbols
        assert "OLDCOIN" not in symbols

    def test_a_retired_instrument_remains_reachable_in_detail(self, client):
        """Une position ouverte peut encore le référencer."""
        retired = Asset.objects.create(
            symbol="OLDCOIN", asset_class="CRYPTO", exchange="BINANCE", is_active=False,
        )

        response = client.get(
            reverse("api-assets-detail", kwargs={"pk": retired.pk})
        )

        assert response.status_code == 200

    def test_search_matches_symbol_and_name(self, client, asset):
        by_symbol = client.get(reverse("api-assets-list"), {"search": "BTC"}).json()
        by_name = client.get(reverse("api-assets-list"), {"search": "Bitcoin"}).json()

        assert by_symbol["count"] == 1
        assert by_name["count"] == 1

    def test_history_is_returned_oldest_first_for_charting(self, client, asset, daily):
        _candle(asset, daily, close="100.00", age_days=3)
        _candle(asset, daily, close="110.00", age_days=2)
        _candle(asset, daily, close="120.00", age_days=1)

        body = client.get(
            reverse("api-assets-candles", kwargs={"pk": asset.pk})
        ).json()

        closes = [row["close"] for row in body["candles"]]
        assert closes == ["100", "110", "120"]
        assert body["freshness"] in {Freshness.LIVE, Freshness.DELAYED, Freshness.STALE}

    def test_history_carries_its_own_freshness(self, client, asset, daily):
        _candle(asset, daily, close="100.00", age_days=150)

        body = client.get(
            reverse("api-assets-candles", kwargs={"pk": asset.pk})
        ).json()

        assert body["freshness"] == Freshness.STALE
        assert body["as_of"] is not None

    def test_the_history_limit_is_bounded(self, client, asset, daily):
        """Une limite non bornée laisserait un client demander la table."""
        for day in range(5):
            _candle(asset, daily, close=f"{100 + day}.00", age_days=day + 1)

        body = client.get(
            reverse("api-assets-candles", kwargs={"pk": asset.pk}), {"limit": "999999"},
        ).json()

        assert len(body["candles"]) == 5

    def test_market_data_requires_authentication(self):
        anonymous = APIClient()

        assert anonymous.get(reverse("api-assets-list")).status_code in (401, 403)


# ─────────────────────────────────────────────────────────────────────────────
#  3. Liste de suivi
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestWatchlist:

    def test_following_an_instrument_is_idempotent(self, client, asset):
        """Le bouton « suivre » ne doit pas produire une erreur de
        contrainte au second clic."""
        first = client.post(
            reverse("api-watchlist-list"), {"asset": asset.pk}, format="json",
        )
        second = client.post(
            reverse("api-watchlist-list"), {"asset": asset.pk}, format="json",
        )

        assert first.status_code == 201
        assert second.status_code == 200
        assert WatchlistItem.objects.filter(asset=asset).count() == 1

    def test_a_retired_instrument_cannot_be_followed(self, client):
        retired = Asset.objects.create(
            symbol="OLDCOIN", asset_class="CRYPTO", exchange="BINANCE", is_active=False,
        )

        response = client.post(
            reverse("api-watchlist-list"), {"asset": retired.pk}, format="json",
        )

        assert response.status_code == 400

    def test_another_users_watchlist_is_invisible(self, client, asset, db):
        intruder = User.objects.create_user(
            username="voisin", email="voisin@leotrade.test", password="StrongPass123!",
        )
        WatchlistItem.objects.create(user=intruder, asset=asset)

        body = client.get(reverse("api-watchlist-list")).json()

        assert body["count"] == 0

    def test_watchlist_quotes_carry_the_same_freshness_contract(
        self, client, asset, daily,
    ):
        _candle(asset, daily, close="100.00", age_days=150)
        client.post(reverse("api-watchlist-list"), {"asset": asset.pk}, format="json")

        rows = client.get(reverse("api-watchlist-quotes")).json()

        assert len(rows) == 1
        assert rows[0]["freshness"] == Freshness.STALE
        assert rows[0]["as_of"] is not None


# ─────────────────────────────────────────────────────────────────────────────
#  Régression : la précision d'affichage ne doit pas tronquer le transport
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestPrecisionIsNotTruncatedForCharting:
    """`Asset.price_precision` vaut 2 par défaut et n'est renseigné nulle
    part. Arrondir les bougies à cette précision avant de les transmettre
    ramenait 300 bougies ADAUSDT à dix cours distincts et 263 bougies
    plates — un mouvement de +60 % rendu comme une ligne horizontale.

    La précision d'affichage est une indication pour le client ; elle n'a
    pas à borner ce que le serveur transmet.
    """

    @pytest.fixture
    def penny(self, db):
        return Asset.objects.create(
            symbol="ADAUSDT", name="Cardano", asset_class="CRYPTO",
            exchange="BINANCE", price_precision=2, is_active=True,
        )

    def test_small_prices_keep_their_distinct_values(self, client, penny, daily):
        for index, close in enumerate(["0.1498", "0.1811", "0.2104", "0.2377"]):
            _candle(penny, daily, close=close, age_days=4 - index)

        body = client.get(
            reverse("api-assets-candles", kwargs={"pk": penny.pk})
        ).json()

        closes = [row["close"] for row in body["candles"]]
        assert len(set(closes)) == 4, (
            f"Quatre cours distincts attendus, reçu {closes} — "
            f"l'arrondi d'affichage a été appliqué au transport."
        )
        assert "0.1498" in closes

    def test_a_candle_does_not_become_flat_through_rounding(
        self, client, penny, daily,
    ):
        _candle(penny, daily, close="0.2377", age_days=1, open_price="0.2104")

        body = client.get(
            reverse("api-assets-candles", kwargs={"pk": penny.pk})
        ).json()
        candle = body["candles"][0]

        assert candle["open"] != candle["close"], (
            "Une bougie dont l'ouverture et la clôture diffèrent de 13 % "
            "ne doit pas sortir plate."
        )

    def test_the_quote_keeps_its_precision_too(self, client, penny, daily):
        _candle(penny, daily, close="0.123456", age_days=0)

        body = client.get(
            reverse("api-assets-quote", kwargs={"pk": penny.pk})
        ).json()

        assert body["price"] == "0.123456"

    def test_the_display_hint_remains_available_to_the_client(self, client, penny):
        """Le client doit pouvoir formater : l'indication reste exposée,
        c'est seulement le serveur qui cesse d'arrondir."""
        body = client.get(
            reverse("api-assets-detail", kwargs={"pk": penny.pk})
        ).json()

        assert body["price_precision"] == 2
