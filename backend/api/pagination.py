"""Pagination par défaut de l'API v1.

Sans pagination, les collections à forte cardinalité (positions, grand livre,
bougies, logs d'inférence) renvoient l'historique complet d'un compte actif :
réponse de plusieurs mégaoctets, client mobile saturé, et une base qui scanne
toute la table. La pagination est donc imposée globalement, pas au cas par cas.
"""

from __future__ import annotations

from collections import OrderedDict

from rest_framework.pagination import CursorPagination, PageNumberPagination
from rest_framework.response import Response


class StandardPageNumberPagination(PageNumberPagination):
    """Pagination par numéro de page, surchargeable par le client.

    `page_size` est plafonné : un client ne peut pas contourner la protection
    en demandant 100 000 éléments.
    """

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 200

    def get_paginated_response(self, data):
        return Response(
            OrderedDict(
                [
                    ("count", self.page.paginator.count),
                    ("page", self.page.number),
                    ("pages", self.page.paginator.num_pages),
                    ("page_size", self.get_page_size(self.request)),
                    ("next", self.get_next_link()),
                    ("previous", self.get_previous_link()),
                    ("results", data),
                ]
            )
        )


class TimeSeriesCursorPagination(CursorPagination):
    """Pagination par curseur pour les flux chronologiques.

    À utiliser sur les collections qui grossissent en continu et que l'on
    parcourt du plus récent au plus ancien (bougies, événements d'exécution,
    notifications, messages d'assistant). Le curseur évite le décalage de
    page quand de nouvelles lignes arrivent pendant la pagination — un
    problème réel ici, puisque ces flux sont alimentés en temps réel.
    """

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
    ordering = "-created_at"
