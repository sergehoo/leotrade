# /Users/ogahserge/Documents/leoTrade/portfolio/services.py
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from itertools import combinations

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from core.realtime import RealtimeBroadcastService
from market.models import Candle
from .models import (
    Portfolio,
    Position,
    PortfolioSnapshot,
    PositionCorrelation,
    CashLedgerEntry,
)

MONEY_QUANT = Decimal("0.01")
PRICE_QUANT = Decimal("0.00000001")


def _to_decimal(value, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _quantize_money(value: Decimal) -> Decimal:
    return _to_decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _quantize_price(value: Decimal) -> Decimal:
    return _to_decimal(value).quantize(PRICE_QUANT, rounding=ROUND_HALF_UP)


def _safe_pct(new_value, old_value):
    new_value = _to_decimal(new_value)
    old_value = _to_decimal(old_value)
    if old_value == 0:
        return 0.0
    return float(((new_value - old_value) / old_value) * Decimal("100"))


class PortfolioAccountingService:
    @staticmethod
    @transaction.atomic
    def add_ledger_entry(
            *,
            portfolio: Portfolio,
            entry_type: str,
            amount: Decimal,
            currency: str | None = None,
            reference_type: str | None = None,
            reference_id: str | None = None,
            description: str | None = None,
            metadata: dict | None = None,
    ) -> CashLedgerEntry:
        amount = _quantize_money(amount)
        if amount == 0:
            raise ValueError("Un mouvement de ledger à zéro est interdit.")

        return CashLedgerEntry.objects.create(
            portfolio=portfolio,
            entry_type=entry_type,
            amount=amount,
            currency=currency or portfolio.base_currency,
            reference_type=reference_type,
            reference_id=reference_id,
            description=description or "",
            metadata=metadata or {},
        )

    @staticmethod
    @transaction.atomic
    def deposit(
            portfolio: Portfolio,
            amount: Decimal,
            description: str = "Dépôt portefeuille",
            metadata: dict | None = None,
    ) -> Portfolio:
        amount = _quantize_money(amount)
        if amount <= 0:
            raise ValueError("Le montant du dépôt doit être positif.")

        PortfolioAccountingService.add_ledger_entry(
            portfolio=portfolio,
            entry_type="DEPOSIT",
            amount=amount,
            description=description,
            metadata=metadata,
        )
        return PortfolioService.recompute_cash_state(portfolio)

    @staticmethod
    @transaction.atomic
    def withdraw(
            portfolio: Portfolio,
            amount: Decimal,
            description: str = "Retrait portefeuille",
            metadata: dict | None = None,
    ) -> Portfolio:
        amount = _quantize_money(amount)
        if amount <= 0:
            raise ValueError("Le montant du retrait doit être positif.")

        portfolio = PortfolioService.recompute_cash_state(portfolio)
        if portfolio.available_cash < amount:
            raise ValueError("Cash disponible insuffisant pour ce retrait.")

        PortfolioAccountingService.add_ledger_entry(
            portfolio=portfolio,
            entry_type="WITHDRAWAL",
            amount=-amount,
            description=description,
            metadata=metadata,
        )
        return PortfolioService.recompute_cash_state(portfolio)

    @staticmethod
    @transaction.atomic
    def lock_cash_for_order(
            portfolio: Portfolio,
            amount: Decimal,
            reference_type: str,
            reference_id: str,
            metadata: dict | None = None,
    ) -> Portfolio:
        amount = _quantize_money(amount)
        if amount <= 0:
            raise ValueError("Le montant à verrouiller doit être positif.")

        # SELECT FOR UPDATE — verrouille la ligne portfolio pour toute la transaction.
        # Sans ce lock, deux workers concurrents peuvent lire le même available_cash
        # et tous les deux approuver un débit, conduisant à un solde négatif.
        portfolio = Portfolio.objects.select_for_update().get(pk=portfolio.pk)
        portfolio = PortfolioService.recompute_cash_state(portfolio)
        if portfolio.available_cash < amount:
            raise ValueError(
                f"Cash disponible insuffisant : {portfolio.available_cash} < {amount}"
            )

        PortfolioAccountingService.add_ledger_entry(
            portfolio=portfolio,
            entry_type="ORDER_LOCK",
            amount=-amount,
            reference_type=reference_type,
            reference_id=reference_id,
            description="Verrouillage de cash pour ordre",
            metadata=metadata,
        )
        return PortfolioService.recompute_cash_state(portfolio)

    @staticmethod
    @transaction.atomic
    def release_cash_from_order(
            portfolio: Portfolio,
            amount: Decimal,
            reference_type: str,
            reference_id: str,
            metadata: dict | None = None,
    ) -> Portfolio:
        amount = _quantize_money(amount)
        if amount <= 0:
            raise ValueError("Le montant à libérer doit être positif.")

        PortfolioAccountingService.add_ledger_entry(
            portfolio=portfolio,
            entry_type="ORDER_RELEASE",
            amount=amount,
            reference_type=reference_type,
            reference_id=reference_id,
            description="Libération de cash d'ordre",
            metadata=metadata,
        )
        return PortfolioService.recompute_cash_state(portfolio)

    @staticmethod
    @transaction.atomic
    def apply_realized_pnl(
            portfolio: Portfolio,
            amount: Decimal,
            reference_type: str = "POSITION",
            reference_id: str | None = None,
            metadata: dict | None = None,
    ) -> Portfolio:
        amount = _quantize_money(amount)
        if amount == 0:
            return PortfolioService.recompute_cash_state(portfolio)

        PortfolioAccountingService.add_ledger_entry(
            portfolio=portfolio,
            entry_type="PNL_REALIZED",
            amount=amount,
            reference_type=reference_type,
            reference_id=reference_id,
            description="PnL réalisé",
            metadata=metadata,
        )
        return PortfolioService.recompute_cash_state(portfolio)

    @staticmethod
    @transaction.atomic
    def apply_fee(
            portfolio: Portfolio,
            amount: Decimal,
            reference_type: str | None = None,
            reference_id: str | None = None,
            metadata: dict | None = None,
    ) -> Portfolio:
        amount = _quantize_money(amount)
        if amount <= 0:
            raise ValueError("Les frais doivent être positifs.")

        PortfolioAccountingService.add_ledger_entry(
            portfolio=portfolio,
            entry_type="FEE",
            amount=-amount,
            reference_type=reference_type,
            reference_id=reference_id,
            description="Frais broker / exécution",
            metadata=metadata,
        )
        return PortfolioService.recompute_cash_state(portfolio)


class PortfolioService:
    @staticmethod
    @transaction.atomic
    def recompute_cash_state(portfolio: Portfolio) -> Portfolio:
        totals = portfolio.ledger_entries.aggregate(total=Sum("amount"))
        ledger_total = _quantize_money(totals["total"] or Decimal("0.00"))

        current_balance = _quantize_money(_to_decimal(portfolio.starting_balance) + ledger_total)

        locked_rows = portfolio.ledger_entries.filter(
            entry_type__in=["ORDER_LOCK", "ORDER_RELEASE"]
        ).aggregate(total=Sum("amount"))
        lock_net = _to_decimal(locked_rows["total"] or Decimal("0.00"))
        locked_cash = _quantize_money(abs(lock_net)) if lock_net < 0 else Decimal("0.00")

        available_cash = _quantize_money(current_balance - locked_cash)
        if available_cash < 0:
            available_cash = Decimal("0.00")

        portfolio.current_balance = current_balance
        portfolio.available_cash = available_cash
        portfolio.locked_cash = locked_cash
        portfolio.save(update_fields=["current_balance", "available_cash", "locked_cash", "updated_at"])
        return portfolio

    @staticmethod
    @transaction.atomic
    def refresh_portfolio_metrics(portfolio: Portfolio) -> Portfolio:
        portfolio = PortfolioService.recompute_cash_state(portfolio)

        open_positions = (
            portfolio.positions
            .filter(status__in=["OPEN", "PARTIALLY_CLOSED"])
            .select_related("asset", "broker_account")
        )

        unrealized = Decimal("0.00")
        realized_positions = Decimal("0.00")
        margin_used = Decimal("0.00")

        for position in open_positions:
            try:
                is_deriv = str(
                    getattr(getattr(position, "broker_account", None), "broker", "") or "").upper() == "DERIV"

                if is_deriv:
                    stake = (
                            _to_decimal(position.margin_used)
                            or _to_decimal(position.notional_value)
                            or _to_decimal(position.exposure_value)
                            or _to_decimal(position.quantity)
                    )

                    if stake <= 0:
                        stake = Decimal("0.00")

                    position.notional_value = _quantize_money(stake)
                    position.exposure_value = _quantize_money(stake)
                    position.margin_used = _quantize_money(stake)

                    # Ne pas recalculer un faux PnL sur price * quantity pour Deriv.
                    position.unrealized_pnl = _quantize_money(position.unrealized_pnl or Decimal("0.00"))
                    position.pnl = _quantize_money(position.pnl or Decimal("0.00"))
                else:
                    position.update_market_metrics()
                    position.notional_value = _quantize_money(position.notional_value)
                    position.exposure_value = _quantize_money(position.exposure_value)
                    position.unrealized_pnl = _quantize_money(position.unrealized_pnl)
                    position.pnl = _quantize_money(position.pnl)
                    position.margin_used = _quantize_money(position.margin_used)

                position.save(update_fields=[
                    "notional_value",
                    "exposure_value",
                    "unrealized_pnl",
                    "pnl",
                    "pnl_percent",
                    "margin_used",
                    "updated_at",
                ])

                unrealized += _to_decimal(position.unrealized_pnl)
                realized_positions += _to_decimal(position.realized_pnl)
                margin_used += _to_decimal(position.margin_used)
            except Exception:
                unrealized += _to_decimal(getattr(position, "unrealized_pnl", 0))
                realized_positions += _to_decimal(getattr(position, "realized_pnl", 0))
                margin_used += _to_decimal(getattr(position, "margin_used", 0))

        ledger_realized = portfolio.ledger_entries.filter(
            entry_type="PNL_REALIZED"
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        total_realized = _quantize_money(_to_decimal(ledger_realized) + realized_positions)
        equity = _quantize_money(portfolio.current_balance + unrealized)

        # Protection contre un ancien max_equity corrompu par des métriques Deriv fantômes.
        if portfolio.current_balance and portfolio.max_equity:
            if _to_decimal(portfolio.max_equity) > (_to_decimal(portfolio.current_balance) * Decimal("10")):
                portfolio.max_equity = portfolio.current_balance

        max_equity = _quantize_money(portfolio.max_equity or Decimal("0.00"))
        if equity > max_equity:
            max_equity = equity

        if max_equity > 0:
            dd = ((max_equity - equity) / max_equity) * Decimal("100")
            current_drawdown_percent = float(max(Decimal("0"), dd))
            previous_max_dd = float(portfolio.max_drawdown_percent or 0.0)

            if previous_max_dd > 100:
                previous_max_dd = current_drawdown_percent

            max_drawdown_percent = max(previous_max_dd, current_drawdown_percent)
        else:
            current_drawdown_percent = 0.0
            max_drawdown_percent = float(portfolio.max_drawdown_percent or 0.0)

        portfolio.unrealized_pnl = _quantize_money(unrealized)
        portfolio.realized_pnl = total_realized
        portfolio.margin_used = _quantize_money(margin_used)
        portfolio.equity = equity
        portfolio.max_equity = max_equity
        portfolio.current_drawdown_percent = current_drawdown_percent
        portfolio.max_drawdown_percent = max_drawdown_percent

        portfolio.save(update_fields=[
            "unrealized_pnl",
            "realized_pnl",
            "margin_used",
            "equity",
            "max_equity",
            "current_drawdown_percent",
            "max_drawdown_percent",
            "updated_at",
        ])
        RealtimeBroadcastService.broadcast_portfolio_update(
            portfolio_id=portfolio.id,
            payload={
                "kind": "metrics_refresh",
                "portfolio_id": portfolio.id,
                "balance": str(portfolio.current_balance),
                "available_cash": str(portfolio.available_cash),
                "locked_cash": str(portfolio.locked_cash),
                "equity": str(portfolio.equity),
                "unrealized_pnl": str(portfolio.unrealized_pnl),
                "realized_pnl": str(portfolio.realized_pnl),
                "margin_used": str(portfolio.margin_used),
                "drawdown": portfolio.current_drawdown_percent,
                "max_drawdown": portfolio.max_drawdown_percent,
            },
        )

        RealtimeBroadcastService.broadcast_dashboard_update(
            user_id=portfolio.user_id,
            payload={
                "kind": "portfolio_metrics",
                "portfolio_id": portfolio.id,
                "equity": str(portfolio.equity),
                "balance": str(portfolio.current_balance),
                "unrealized_pnl": str(portfolio.unrealized_pnl),
                "drawdown": portfolio.current_drawdown_percent,
            },
        )
        return portfolio

    @staticmethod
    @transaction.atomic
    def create_snapshot(portfolio: Portfolio):
        portfolio = PortfolioService.refresh_portfolio_metrics(portfolio)
        now = timezone.now()

        daily_reference = (
            portfolio.snapshots
            .filter(snapshot_time__date=now.date())
            .order_by("snapshot_time")
            .first()
        )
        monthly_reference = (
            portfolio.snapshots
            .filter(snapshot_time__year=now.year, snapshot_time__month=now.month)
            .order_by("snapshot_time")
            .first()
        )

        daily_return = _safe_pct(portfolio.equity, daily_reference.equity if daily_reference else None)
        monthly_return = _safe_pct(portfolio.equity, monthly_reference.equity if monthly_reference else None)

        snapshot = PortfolioSnapshot.objects.create(
            portfolio=portfolio,
            snapshot_time=now,
            balance=portfolio.current_balance,
            available_cash=portfolio.available_cash,
            locked_cash=portfolio.locked_cash,
            equity=portfolio.equity,
            unrealized_pnl=portfolio.unrealized_pnl,
            realized_pnl=portfolio.realized_pnl,
            margin_used=portfolio.margin_used,
            drawdown_percent=float(portfolio.current_drawdown_percent or 0.0),
            daily_return_percent=daily_return,
            monthly_return_percent=monthly_return,
        )

        RealtimeBroadcastService.broadcast_portfolio_update(
            portfolio_id=portfolio.id,
            payload={
                "kind": "snapshot_created",
                "portfolio_id": portfolio.id,
                "snapshot_id": snapshot.id,
                "snapshot_time": snapshot.snapshot_time.isoformat(),
                "equity": str(snapshot.equity),
                "balance": str(snapshot.balance),
                "drawdown_percent": snapshot.drawdown_percent,
            },
        )

        return snapshot

    @staticmethod
    @transaction.atomic
    def set_default_portfolio(portfolio: Portfolio):
        Portfolio.objects.filter(
            user=portfolio.user,
            is_default=True,
        ).exclude(pk=portfolio.pk).update(is_default=False)

        portfolio.is_default = True
        portfolio.save(update_fields=["is_default", "updated_at"])
        return portfolio

    @staticmethod
    def asset_class_exposure(portfolio: Portfolio):
        rows = (
            portfolio.positions
            .filter(status__in=["OPEN", "PARTIALLY_CLOSED"])
            .select_related("asset", "broker_account")
        )

        result = {}
        total = Decimal("0.00")

        for pos in rows:
            is_deriv = str(getattr(getattr(pos, "broker_account", None), "broker", "") or "").upper() == "DERIV"

            if is_deriv:
                value = (
                        _to_decimal(getattr(pos, "margin_used", None), default="0")
                        or _to_decimal(getattr(pos, "notional_value", None), default="0")
                        or _to_decimal(getattr(pos, "quantity", None), default="0")
                )
            else:
                value = _to_decimal(getattr(pos, "exposure_value", None), default="0")
            asset = getattr(pos, "asset", None)
            asset_class = getattr(asset, "asset_class", None) or "UNKNOWN"

            result.setdefault(asset_class, Decimal("0.00"))
            result[asset_class] += value
            total += value

        payload = []
        for key, value in result.items():
            pct = float((value / total) * Decimal("100")) if total > 0 else 0.0
            payload.append({
                "asset_class": key,
                "value": float(_quantize_money(value)),
                "percent": pct,
            })

        return payload

    @staticmethod
    @transaction.atomic
    def position_correlation_matrix(portfolio: Portfolio, timeframe_code="1d", lookback_bars=90):
        open_positions = list(
            portfolio.positions
            .filter(status__in=["OPEN", "PARTIALLY_CLOSED"])
            .select_related("asset", "broker_account")
        )

        unique_assets = []
        seen_asset_ids = set()

        for position in open_positions:
            asset = getattr(position, "asset", None)
            if asset and asset.id not in seen_asset_ids:
                unique_assets.append(asset)
                seen_asset_ids.add(asset.id)

        PositionCorrelation.objects.filter(
            portfolio=portfolio,
            timeframe_code=timeframe_code,
            lookback_bars=lookback_bars,
        ).delete()

        results = []

        for asset_a, asset_b in combinations(unique_assets, 2):
            candles_a = list(
                Candle.objects
                .filter(asset=asset_a, timeframe__code=timeframe_code)
                .order_by("-open_time")
                .values_list("close", flat=True)[:lookback_bars]
            )
            candles_b = list(
                Candle.objects
                .filter(asset=asset_b, timeframe__code=timeframe_code)
                .order_by("-open_time")
                .values_list("close", flat=True)[:lookback_bars]
            )

            series_a = list(reversed([float(_to_decimal(x)) for x in candles_a if x is not None]))
            series_b = list(reversed([float(_to_decimal(x)) for x in candles_b if x is not None]))

            n = min(len(series_a), len(series_b))
            if n < 5:
                corr = 0.0
            else:
                a = series_a[-n:]
                b = series_b[-n:]
                mean_a = sum(a) / n
                mean_b = sum(b) / n

                cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
                var_a = sum((x - mean_a) ** 2 for x in a)
                var_b = sum((y - mean_b) ** 2 for y in b)

                if var_a <= 0 or var_b <= 0:
                    corr = 0.0
                else:
                    corr = cov / ((var_a ** 0.5) * (var_b ** 0.5))

            row = PositionCorrelation.objects.create(
                portfolio=portfolio,
                asset_a=asset_a,
                asset_b=asset_b,
                timeframe_code=timeframe_code,
                lookback_bars=lookback_bars,
                correlation_value=corr,
            )
            results.append(row)

        return results
