"""
portfolio/services_equity_curve.py
==================================

Série de valorisation d'un portefeuille.

Un graphique affirme plus fort qu'un nombre. Relier cinq points espacés
de six semaines produit une ligne continue, et cette ligne raconte une
trajectoire qui n'a jamais été mesurée : l'œil lit une tendance là où il
n'y a que des îlots.

Le service ne décide donc pas seulement *quoi* tracer, mais *s'il y a
lieu de tracer*. Il renvoie la série accompagnée de quoi juger :
nombre de points, intervalle couvert, écart médian entre deux points, et
un verdict explicite. C'est l'interface qui refuse de dessiner, mais
c'est le serveur qui lui donne les moyens de refuser.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.utils import timezone

log = logging.getLogger("leotrade.portfolio.equity_curve")

#: En deçà, une ligne relierait des points trop isolés pour signifier
#: quoi que ce soit. Deux points font un segment, pas une trajectoire.
MIN_POINTS_FOR_CURVE = 5

#: Au-delà, l'intervalle TYPIQUE entre deux mesures est tel que
#: l'interpolation invente plus qu'elle ne montre.
MAX_MEDIAN_GAP_SECONDS = 36 * 3600

#: Au-delà, un SEUL trou suffit à disqualifier la série.
#:
#: La médiane est par construction aveugle à un trou unique : 365 points
#: quotidiens dont le milieu comporte une interruption de huit mois
#: gardent une médiane de 24 h. Pire, l'axe des temps d'un graphique
#: boursier est ordinal — deux points consécutifs sont espacés d'une
#: largeur de barre, qu'ils soient séparés d'une heure ou d'un an. Le
#: trou est donc dessiné à la largeur d'un point, et le segment qui
#: l'enjambe a la même pente apparente que ses voisins.
MAX_SINGLE_GAP_SECONDS = 7 * 24 * 3600

#: Au-delà, la série ne décrit plus l'état actuel du portefeuille.
STALE_AFTER_SECONDS = 7 * 24 * 3600


def _money(value) -> str:
    return str(Decimal(value or 0).quantize(Decimal("0.01")))


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


class EquityCurveService:

    @staticmethod
    def build(portfolio, limit: int = 365) -> dict:
        from portfolio.models import PortfolioSnapshot

        limit = max(2, min(int(limit or 365), 2000))
        rows = list(
            PortfolioSnapshot.objects
            .filter(portfolio=portfolio)
            .order_by("-snapshot_time")
            .values("snapshot_time", "equity", "balance", "unrealized_pnl",
                    "realized_pnl", "drawdown_percent")[:limit]
        )
        rows.reverse()

        points = [
            {
                "at": row["snapshot_time"],
                "equity": _money(row["equity"]),
                "balance": _money(row["balance"]),
                "unrealized_pnl": _money(row["unrealized_pnl"]),
                "realized_pnl": _money(row["realized_pnl"]),
                "drawdown_percent": float(row["drawdown_percent"] or 0.0),
            }
            for row in rows
        ]

        gaps = [
            (rows[index]["snapshot_time"] - rows[index - 1]["snapshot_time"]).total_seconds()
            for index in range(1, len(rows))
        ]
        median_gap = _median(gaps)
        max_gap = max(gaps) if gaps else 0.0

        first_at = rows[0]["snapshot_time"] if rows else None
        last_at = rows[-1]["snapshot_time"] if rows else None
        age = (timezone.now() - last_at).total_seconds() if last_at else None

        reasons = []
        if len(points) < MIN_POINTS_FOR_CURVE:
            reasons.append("TOO_FEW_POINTS")
        if median_gap and median_gap > MAX_MEDIAN_GAP_SECONDS:
            reasons.append("GAPS_TOO_WIDE")
        if max_gap and max_gap > MAX_SINGLE_GAP_SECONDS:
            # Un seul trou suffit : l'axe ordinal le dessinerait à la
            # largeur d'un point, invisible à l'œil et invisible à la
            # médiane.
            reasons.append("INTERRUPTED")

        is_stale = age is not None and age > STALE_AFTER_SECONDS

        return {
            "portfolio_id": portfolio.pk,
            "base_currency": portfolio.base_currency,
            "points": points,
            "point_count": len(points),
            "first_at": first_at,
            "last_at": last_at,
            "age_seconds": int(age) if age is not None else None,
            "median_gap_seconds": int(median_gap) if median_gap else None,
            # Le plus grand trou de la série : c'est lui qui décide, pas la
            # médiane, dès qu'il s'agit d'une interruption.
            "max_gap_seconds": int(max_gap) if max_gap else None,
            # Une série traçable mais ancienne décrit un état révolu. Le
            # verdict de traçabilité ne dit rien de la fraîcheur : les deux
            # sont indépendants et doivent être annoncés séparément.
            "is_stale": is_stale,
            # Verdict explicite : l'interface n'a pas à redériver le seuil,
            # et deux clients ne doivent pas décider différemment.
            "is_plottable": not reasons,
            "not_plottable_reasons": reasons,
            "minimum_points": MIN_POINTS_FOR_CURVE,
        }
