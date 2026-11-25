"""
portfolio/tasks.py
==================

Tâches Celery liées au portefeuille :
  - update_marks_task : refresh Position.current_price à partir du cache Redis
    qui contient les derniers prix vus (alimenté par les imports candles + ticks
    broker). C'est le moteur du PnL latent en temps réel.

  - broadcast_open_positions_task : pousse périodiquement l'état des positions
    ouvertes vers les WebSocket Channels (utile en complément du push-on-fill,
    pour que le dashboard reste cohérent même en cas de désync).
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from celery import shared_task

from core.redis_lock import single_run


log = logging.getLogger("lyneci.portfolio.tasks")


def _to_decimal(v) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


# =============================================================================
# Mark-to-market : Position.current_price ← cache Redis "mark:{symbol}"
# =============================================================================

@shared_task(name="portfolio.tasks.update_marks_task", bind=True)
def update_marks_task(self):
    """
    Pour chaque Position OPEN/PARTIALLY_CLOSED, met à jour `current_price`
    à partir de la clé Redis ``mark:{symbol}`` (alimentée par les feeds
    market data + ticks broker). Puis broadcast le nouvel état au WS portfolio.

    Idempotent. Lock Redis pour éviter chevauchement.
    """
    from django.core.cache import cache

    from portfolio.models import Position, Portfolio
    from portfolio.services import PortfolioService
    from core.realtime import RealtimeBroadcastService

    with single_run("lock:update_marks_task", ttl=25) as acquired:
        if not acquired:
            return {"skipped": True}

        portfolios_touched = set()
        n_updated = 0

        positions_qs = Position.objects.filter(
            status__in=["OPEN", "PARTIALLY_CLOSED"],
        ).only(
            "id", "symbol", "side", "quantity",
            "average_entry_price", "current_price", "portfolio_id",
        )

        for pos in positions_qs.iterator(chunk_size=200):
            mp_raw = cache.get(f"mark:{pos.symbol}")
            mp = _to_decimal(mp_raw)
            if mp is None or mp <= 0:
                continue
            if pos.current_price == mp:
                continue

            old = pos.current_price
            pos.current_price = mp
            pos.save(update_fields=["current_price", "updated_at"])
            portfolios_touched.add(pos.portfolio_id)
            n_updated += 1

            # Push la position en live aux clients du portfolio
            try:
                qty = pos.quantity or Decimal("0")
                entry = pos.average_entry_price or Decimal("0")
                sign = Decimal("1") if pos.side == "LONG" else Decimal("-1")
                unrealized = ((mp - entry) * qty * sign) if (qty and entry) else Decimal("0")
                RealtimeBroadcastService.broadcast_position_update(
                    portfolio_id=pos.portfolio_id,
                    position={
                        "id": pos.id,
                        "symbol": pos.symbol,
                        "side": pos.side,
                        "quantity": str(qty),
                        "avg_entry_price": str(entry),
                        "mark_price": str(mp),
                        "previous_mark_price": str(old) if old else None,
                        "unrealized_pnl": str(unrealized.quantize(Decimal("0.01"))),
                    },
                )
            except Exception as exc:  # pragma: no cover
                log.warning(
                    "update_marks_task.broadcast_failed position_id=%s err=%s",
                    pos.id, exc,
                )

        # Refresh les métriques agrégées des portfolios impactés
        for pid in portfolios_touched:
            try:
                pf = Portfolio.objects.get(pk=pid)
                PortfolioService.refresh_portfolio_metrics(pf)
            except Exception as exc:
                log.warning(
                    "update_marks_task.metrics_refresh_failed portfolio_id=%s err=%s",
                    pid, exc,
                )

        log.info("update_marks_task.done updated=%s portfolios=%s", n_updated, len(portfolios_touched))
        return {"updated": n_updated, "portfolios": len(portfolios_touched)}


# =============================================================================
# Broadcast périodique de l'état des positions (filet)
# =============================================================================

@shared_task(name="portfolio.tasks.broadcast_open_positions_task", bind=True)
def broadcast_open_positions_task(self):
    """
    Tous les `intervalle`, broadcast l'état complet des positions ouvertes
    pour chaque portfolio actif. Utile pour rattraper un client qui aurait
    raté un message live.
    """
    from portfolio.models import Position, Portfolio
    from core.realtime import RealtimeBroadcastService

    with single_run("lock:broadcast_open_positions_task", ttl=25) as acquired:
        if not acquired:
            return {"skipped": True}

        n_pf = 0
        for pf in Portfolio.objects.filter(is_active=True).only("id"):
            positions = Position.objects.filter(
                portfolio_id=pf.id,
                status__in=["OPEN", "PARTIALLY_CLOSED"],
            ).only(
                "id", "symbol", "side", "quantity",
                "average_entry_price", "current_price", "unrealized_pnl",
            )
            payload = {
                "kind": "positions_snapshot",
                "positions": [
                    {
                        "id": p.id,
                        "symbol": p.symbol,
                        "side": p.side,
                        "quantity": str(p.quantity),
                        "avg_entry_price": str(p.average_entry_price or 0),
                        "mark_price": str(p.current_price or 0),
                        "unrealized_pnl": str(p.unrealized_pnl or 0),
                    }
                    for p in positions
                ],
            }
            try:
                RealtimeBroadcastService.broadcast_portfolio_update(
                    portfolio_id=pf.id, payload=payload,
                )
                n_pf += 1
            except Exception as exc:
                log.warning(
                    "broadcast_open_positions_task.broadcast_failed pf_id=%s err=%s",
                    pf.id, exc,
                )
        return {"portfolios": n_pf}
