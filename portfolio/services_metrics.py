"""
portfolio/services_metrics.py
=============================

Service de calcul LIVE des métriques d'un portfolio.

Règle : ces métriques ne sont JAMAIS persistées comme champs courants
(seulement comme PortfolioSnapshot horodatés). Elles sont recalculées
à la demande, à partir du ledger + des prix marché courants.

    balance      = starting_balance + Σ CashLedgerEntry.amount
    realized_pnl = Σ Trade.realized_pnl
    unrealized   = Σ_pos (mark_price - avg_entry) * qty * sign(side)
    equity       = balance + unrealized
    used_margin  = Σ_pos notional / leverage
    free_margin  = equity - used_margin
    margin_level = equity / used_margin * 100   (None si pas de positions)
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from decimal import Decimal
from typing import Iterable

from django.db.models import Sum

from portfolio.models import CashLedgerEntry, Portfolio, Position


@dataclass
class PortfolioMetrics:
    portfolio_id: int
    currency: str

    balance: Decimal              # cash réalisé (somme ledger + starting)
    realized_pnl: Decimal         # Σ Trade.realized_pnl
    unrealized_pnl: Decimal       # mark-to-market sur positions ouvertes
    equity: Decimal               # balance + unrealized
    used_margin: Decimal
    free_margin: Decimal
    margin_level: Decimal | None  # en %
    open_positions: int

    def as_dict(self) -> dict:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, Decimal):
                d[k] = str(v)
        return d


class PortfolioMetricsService:

    @staticmethod
    def compute_live(
        portfolio_id: int,
        mark_prices: dict[str, Decimal] | None = None,
    ) -> PortfolioMetrics:
        """
        Calcule les métriques en mémoire, sans aucune écriture DB.

        :param mark_prices: dict {symbol: mark_price}. Si non fourni pour un symbole,
                            on tombe back sur position.current_price puis avg_entry.
        """
        from portfolio.models_trade import Trade  # import local pour éviter circulaire

        mark_prices = mark_prices or {}
        portfolio = Portfolio.objects.get(pk=portfolio_id)

        # 1. Balance via ledger
        starting = portfolio.starting_balance or Decimal("0")
        ledger_total = (
            CashLedgerEntry.objects
            .filter(portfolio_id=portfolio_id)
            .aggregate(s=Sum("amount"))["s"]
            or Decimal("0")
        )
        balance = (starting + ledger_total).quantize(Decimal("0.01"))

        # 2. Realized PnL = Σ Trade.realized_pnl (source de vérité unique)
        realized_pnl = (
            Trade.objects
            .filter(portfolio_id=portfolio_id)
            .aggregate(s=Sum("realized_pnl"))["s"]
            or Decimal("0")
        ).quantize(Decimal("0.01"))

        # 3. Unrealized via positions ouvertes + mark prices
        unrealized = Decimal("0")
        used_margin = Decimal("0")
        n_open = 0
        for pos in Position.objects.filter(
            portfolio_id=portfolio_id,
            status__in=["OPEN", "PARTIALLY_CLOSED"],
        ).only(
            "symbol", "side", "quantity",
            "average_entry_price", "current_price",
            "notional_value", "leverage",
        ):
            n_open += 1
            qty = pos.quantity or Decimal("0")
            entry = pos.average_entry_price or Decimal("0")
            mp = mark_prices.get(pos.symbol) or pos.current_price or entry
            sign = Decimal("1") if pos.side == "LONG" else Decimal("-1")
            unrealized += ((mp - entry) * qty * sign)

            lev = pos.leverage or Decimal("1")
            if lev <= 0:
                lev = Decimal("1")
            used_margin += (pos.notional_value or Decimal("0")) / lev

        unrealized = unrealized.quantize(Decimal("0.01"))
        used_margin = used_margin.quantize(Decimal("0.01"))

        equity = (balance + unrealized).quantize(Decimal("0.01"))
        free_margin = (equity - used_margin).quantize(Decimal("0.01"))

        if used_margin > 0:
            margin_level = (equity / used_margin * Decimal("100")).quantize(Decimal("0.01"))
        else:
            margin_level = None

        return PortfolioMetrics(
            portfolio_id=portfolio_id,
            currency=portfolio.base_currency,
            balance=balance,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized,
            equity=equity,
            used_margin=used_margin,
            free_margin=free_margin,
            margin_level=margin_level,
            open_positions=n_open,
        )
