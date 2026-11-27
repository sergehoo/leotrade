"""
tests_phase/test_realtime_contract.py
=====================================

Ce que le canal `ws/portfolio/<id>/` promet aux clients.

Six canaux temps réel existent depuis l'origine — portefeuille, ordres,
notifications, tableau de bord, radar IA, bougies — avec leurs
émetteurs. Aucun des deux nouveaux clients ne s'y connectait : le web et
le mobile rechargeaient à la main ce que le serveur leur poussait déjà.

Maintenant qu'ils écoutent, la FORME de la charge utile est un contrat.
Un champ renommé ou un montant passé en nombre ne casserait rien côté
serveur, et ferait silencieusement disparaître une valeur de deux
interfaces.

Les montants voyagent en `str` : le serveur calcule en `Decimal`, et ni
TypeScript ni Dart n'ont d'équivalent natif. Un `float` dans la charge
utile, c'est une valorisation arrondie à l'insu de tout le monde.
"""

from decimal import Decimal
from unittest import mock

import pytest
from django.contrib.auth import get_user_model

from portfolio.services import PortfolioService
from portfolio.services_onboarding import PaperOnboardingService

User = get_user_model()

#: Champs que `usePortfolioRealtime.ts` et `portfolio_realtime.dart`
#: lisent sur un `metrics_refresh`.
METRICS_FIELDS = [
    "equity",
    "available_cash",
    "locked_cash",
    "unrealized_pnl",
    "realized_pnl",
]


@pytest.fixture
def portfolio(db):
    user = User.objects.create_user(
        username="flux", email="flux@leotrade.test", password="StrongPass123!",
    )
    return PaperOnboardingService.provision(user)


def _broadcasts(portfolio):
    """Charges utiles envoyées par un recalcul de métriques."""
    with mock.patch(
        "core.realtime.RealtimeBroadcastService.broadcast_portfolio_update"
    ) as sent:
        PortfolioService.refresh_portfolio_metrics(portfolio)
    return [call.kwargs for call in sent.call_args_list]


@pytest.mark.django_db
class TestMetricsRefresh:

    def test_a_refresh_reaches_the_portfolio_channel(self, portfolio):
        calls = _broadcasts(portfolio)

        assert calls, "un recalcul doit prévenir les clients branchés"
        assert calls[0]["portfolio_id"] == portfolio.pk

    def test_the_payload_is_labelled(self, portfolio):
        """Les clients aiguillent sur `kind` : sans lui, ils ignorent tout."""
        payload = _broadcasts(portfolio)[0]["payload"]

        assert payload["kind"] == "metrics_refresh"

    @pytest.mark.parametrize("field", METRICS_FIELDS)
    def test_every_field_the_clients_read_is_present(self, portfolio, field):
        payload = _broadcasts(portfolio)[0]["payload"]

        assert field in payload, (
            f"`{field}` est lu par les deux clients ; absent, la valeur "
            "chargée en REST reste affichée sans que rien ne le dise"
        )

    @pytest.mark.parametrize("field", METRICS_FIELDS)
    def test_amounts_travel_as_strings(self, portfolio, field):
        """Un `float` ici, c'est une valorisation arrondie en silence."""
        value = _broadcasts(portfolio)[0]["payload"][field]

        assert isinstance(value, str), f"`{field}` arrive en {type(value).__name__}"
        # Et c'est bien un nombre, pas une chaîne décorative.
        Decimal(value)


@pytest.mark.django_db
class TestPositionUpdate:

    def test_the_position_payload_carries_an_identifier(self, portfolio):
        """Sans `id`, un correctif ne sait pas quelle ligne corriger.

        Les deux clients l'exigent et ignorent le message sinon : c'est
        préférable à corriger la mauvaise position.
        """
        from core.realtime import RealtimeBroadcastService

        with mock.patch.object(RealtimeBroadcastService, "_send") as send:
            RealtimeBroadcastService.broadcast_position_update(
                portfolio_id=portfolio.pk,
                position={"id": 1, "mark_price": "100.00"},
            )

        group, event_type, payload = send.call_args.args
        assert group == f"portfolio_{portfolio.pk}"
        assert event_type == "position.update"
        assert payload["position"]["id"] == 1
