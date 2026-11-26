"""
tests_phase/test_api_route_paths.py
===================================

Le chemin servi, et non celui que ``reverse()`` fabrique.

DRF dérive deux noms différents d'une même méthode décorée par ``@action``
(rest_framework/decorators.py) ::

    func.url_path = url_path if url_path else func.__name__
    func.url_name = url_name if url_name else func.__name__.replace('_', '-')

Le chemin garde les soulignés ; le nom de route les remplace par des
tirets. Une suite écrite avec ``reverse("api-…-set-default")`` passe donc
au vert sur ``/portfolios/3/set_default/`` — pendant que le web et le
mobile, qui écrivent tous deux ``set-default``, reçoivent un 404 ou un
405. Les tests validaient une route qu'aucun client n'appelait.

Trois actions étaient dans ce cas et sont mortes en production :
« Définir par défaut », « Lever l'arrêt d'urgence » et « Recalculer les
états de risque ».

Ce module vise donc le chemin LITTÉRAL, celui que le client tape.
"""

import re

import pytest
from django.urls import get_resolver

API_PREFIX = "api/v1/"

# Les parties variables d'un motif portent légitimement des soulignés —
# un groupe nommé ``(?P<portfolio_id>\d+)`` comme un convertisseur
# ``<drf_format_suffix:format>``. Seul le texte littéral du chemin, celui
# que le client tape, est examiné.
PLACEHOLDER = re.compile(r"\(\?P<[^>]+>[^)]*\)|<[^>]+>")


def _api_route_patterns():
    """Chaque chemin complet servi sous /api/v1/, en texte."""
    found = []

    def walk(patterns, prefix=""):
        for entry in patterns:
            piece = str(entry.pattern)
            if hasattr(entry, "url_patterns"):
                walk(entry.url_patterns, prefix + piece)
            else:
                found.append(prefix + piece)

    walk(get_resolver().url_patterns)
    return [p for p in found if API_PREFIX in p]


def test_no_served_api_path_contains_an_underscore():
    """Un souligné dans un chemin servi signale un ``@action`` sans ``url_path``.

    La convention du projet est le tiret — ``provision-paper``,
    ``equity-curve``, ``test-connection``, ``set-default``. Une action qui
    oublie ``url_path`` sort du lot sans que rien ne le signale, parce que
    ``reverse()`` continue de résoudre.
    """
    offenders = []
    for pattern in _api_route_patterns():
        literal = PLACEHOLDER.sub("", pattern)
        if "_" in literal:
            offenders.append(pattern)

    assert offenders == [], (
        "Ces chemins sont servis avec des soulignés alors que les clients "
        "écrivent des tirets — ajouter url_path=\"…\" sur le @action :\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.parametrize(
    "literal_path",
    [
        "/api/v1/kill-switch-events/resolve-for-portfolio/",
        "/api/v1/risk-utils/refresh-states/",
        "/api/v1/portfolios/1/set-default/",
        "/api/v1/risk-profiles/1/set-default/",
        "/api/v1/portfolios/1/import-live/",
        "/api/v1/portfolios/1/compute-correlations/",
        "/api/v1/orders/create-manual/",
        "/api/v1/orders/reconcile-portfolio/",
        "/api/v1/recommendations/generate-for-portfolio/",
    ],
)
def test_the_literal_path_the_clients_write_is_routable(literal_path):
    """``resolve()`` sur la chaîne exacte, jamais ``reverse()``.

    C'est la seule forme de vérification qui aurait attrapé le défaut :
    ``reverse()`` part du nom de route et ne peut pas, par construction,
    produire un chemin qui n'existe pas.
    """
    from django.urls import Resolver404, resolve

    try:
        resolve(literal_path)
    except Resolver404:  # pragma: no cover - le message importe
        pytest.fail(
            f"{literal_path} n'est routable par aucun motif. "
            "Les clients web et mobile écrivent cette URL."
        )
