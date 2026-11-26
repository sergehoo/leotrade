"""
portfolio/services_summary.py
=============================

Synthèse consolidée d'un portefeuille : P&L, exposition, répartition
des positions ouvertes.

Les trois surfaces (Django, React, Flutter) calculaient chacune leur
version de ces agrégats. Les faire diverger sur un chiffre de P&L est la
manière la plus sûre de perdre la confiance de l'utilisateur, et la plus
difficile à diagnostiquer après coup.

Tous les montants sortent en `str`. Le backend calcule en `Decimal` ;
ni TypeScript ni Dart n'ont d'équivalent natif, et les convertir en
flottant pour les transporter rouvrirait les erreurs d'arrondi que le
`Decimal` sert à éviter.
"""

from __future__ import annotations

from decimal import Decimal

ZERO = Decimal("0.00")


def _money(value) -> str:
    return str(Decimal(value or 0).quantize(Decimal("0.01")))


def _percent(numerator: Decimal, denominator: Decimal) -> str:
    if not denominator:
        return "0.00"
    return str(((numerator / denominator) * Decimal("100")).quantize(Decimal("0.01")))


class PortfolioSummaryService:

    @staticmethod
    def build(portfolio) -> dict:
        from portfolio.models import Position
        from portfolio.services import PortfolioService

        broker = getattr(portfolio, "broker_account", None)
        trading_mode = getattr(broker, "mode", "PAPER")
        is_simulated = (
            broker is None
            or trading_mode == "PAPER"
            or getattr(broker, "broker", None) == "SIMULATION"
        )

        positions = list(
            Position.objects.filter(portfolio=portfolio, status="OPEN")
            .only("side", "unrealized_pnl", "exposure_value")
        )

        unrealized = Decimal(portfolio.unrealized_pnl or ZERO)
        realized = Decimal(portfolio.realized_pnl or ZERO)
        starting = Decimal(portfolio.starting_balance or ZERO)
        equity = Decimal(portfolio.equity or ZERO)

        total_pnl = unrealized + realized
        exposure = sum(
            (Decimal(p.exposure_value or ZERO) for p in positions), ZERO,
        )

        try:
            asset_class_exposure = PortfolioService.asset_class_exposure(portfolio)
        except Exception:
            # Un agrégat secondaire ne doit pas faire échouer la synthèse :
            # l'utilisateur perdrait l'accès à son P&L à cause d'un
            # graphique de répartition.
            asset_class_exposure = []

        return {
            "portfolio_id": portfolio.pk,
            "base_currency": portfolio.base_currency,
            "trading_mode": trading_mode,
            "is_simulated": is_simulated,

            "equity": _money(equity),
            "current_balance": _money(portfolio.current_balance),
            "available_cash": _money(portfolio.available_cash),
            "locked_cash": _money(portfolio.locked_cash),
            "margin_used": _money(portfolio.margin_used),

            "unrealized_pnl": _money(unrealized),
            "realized_pnl": _money(realized),
            "total_pnl": _money(total_pnl),
            # Rapporté au capital de départ, pas à l'équité courante :
            # rapporter un gain à une équité qui inclut déjà ce gain
            # sous-estime systématiquement la performance.
            "total_pnl_percent": _percent(total_pnl, starting),

            "current_drawdown_percent": float(portfolio.current_drawdown_percent or 0.0),
            "max_drawdown_percent": float(portfolio.max_drawdown_percent or 0.0),

            "open_positions": len(positions),
            "long_positions": sum(1 for p in positions if p.side == "LONG"),
            "short_positions": sum(1 for p in positions if p.side == "SHORT"),
            "winning_positions": sum(
                1 for p in positions if Decimal(p.unrealized_pnl or ZERO) > 0
            ),
            "losing_positions": sum(
                1 for p in positions if Decimal(p.unrealized_pnl or ZERO) < 0
            ),

            "exposure_value": _money(exposure),
            "exposure_percent": _percent(exposure, equity),
            "asset_class_exposure": asset_class_exposure,
        }
