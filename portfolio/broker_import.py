from __future__ import annotations

from decimal import Decimal
from django.db import transaction
from django.utils import timezone

from market.models import Asset
from brokers.models import BrokerAccount
from .models import Portfolio, Position
from .services import PortfolioService, PortfolioAccountingService
from infrastructure.broker_clients.gateway import BrokerGateway

def _d(value, default="0"):
    try:
        if value is None:
            return Decimal(default)
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


class BrokerImportService:
    @staticmethod
    def _get_or_create_asset(symbol: str):
        asset = Asset.objects.filter(symbol=symbol).first()
        if asset:
            return asset
        return Asset.objects.create(
            symbol=symbol,
            name=symbol,
            asset_class="CRYPTO",
            is_active=True,
        )

    @staticmethod
    def _upsert_position_from_payload(
        portfolio: Portfolio,
        broker_account: BrokerAccount,
        payload: dict,
    ) -> Position:
        symbol = str(payload.get("symbol") or "").strip()
        if not symbol:
            raise ValueError("Payload broker invalide: symbol manquant.")

        asset = BrokerImportService._get_or_create_asset(symbol)

        quantity = abs(_d(payload.get("quantity")))
        side = str(payload.get("side") or "LONG").upper()
        if side not in {"LONG", "SHORT"}:
            side = "LONG"

        entry_price = _d(payload.get("entry_price"))
        current_price = _d(payload.get("current_price"), default=str(entry_price or "0"))
        average_entry_price = _d(payload.get("average_entry_price"), default=str(entry_price or "0"))
        leverage = _d(payload.get("leverage"), default="1")
        margin_used = _d(payload.get("margin_used"), default="0")
        broker_position_id = str(payload.get("broker_position_id") or "").strip() or None
        cost_basis_status = str(payload.get("cost_basis_status") or "UNKNOWN").upper()
        if cost_basis_status not in {"KNOWN", "ESTIMATED", "UNKNOWN"}:
            cost_basis_status = "UNKNOWN"

        defaults = {
            "portfolio": portfolio,
            "broker_account": broker_account,
            "asset": asset,
            "asset_name": getattr(asset, "name", symbol),
            "side": side,
            "quantity": quantity,
            "entry_price": entry_price,
            "average_entry_price": average_entry_price or entry_price,
            "current_price": current_price,
            "leverage": leverage,
            "margin_used": margin_used,
            "status": "OPEN",
            "source": "IMPORTED",
            "cost_basis_status": cost_basis_status,
            "opened_at": timezone.now(),
            "metadata": payload,
        }

        if broker_position_id:
            position, created = Position.objects.update_or_create(
                portfolio=portfolio,
                broker_position_id=broker_position_id,
                defaults=defaults,
            )
        else:
            position, created = Position.objects.update_or_create(
                portfolio=portfolio,
                symbol=symbol,
                status="OPEN",
                source="IMPORTED",
                defaults=defaults,
            )

        position.update_market_metrics()
        position.save(update_fields=[
            "asset",
            "asset_name",
            "side",
            "quantity",
            "entry_price",
            "average_entry_price",
            "current_price",
            "leverage",
            "margin_used",
            "status",
            "source",
            "cost_basis_status",
            "notional_value",
            "exposure_value",
            "unrealized_pnl",
            "pnl",
            "pnl_percent",
            "metadata",
            "updated_at",
        ])
        return position

    @staticmethod
    def _fetch_remote_cash(broker_account: BrokerAccount):
        client = BrokerGateway(broker_account)
        balances = client.fetch_balances()
        if not balances:
            return None

        preferred = broker_account.deriv_currency or "USD"
        for bal in balances:
            if bal.currency == preferred:
                return bal.available

        return balances[0].available

    @staticmethod
    def fetch_live_positions(broker_account: BrokerAccount) -> list[dict]:
        client = BrokerGateway(broker_account)
        positions = client.fetch_positions()

        payloads = []
        for p in positions:
            payloads.append({
                "symbol": p.symbol,
                "side": p.side,
                "quantity": p.quantity,
                "entry_price": p.entry_price,
                "current_price": p.current_price,
                "average_entry_price": p.average_entry_price,
                "leverage": p.leverage,
                "margin_used": p.margin_used,
                "broker_position_id": p.broker_position_id,
                "cost_basis_status": p.cost_basis_status,
                "metadata": p.metadata,
            })
        return payloads

    @staticmethod
    @transaction.atomic
    def import_live_positions(portfolio: Portfolio):
        broker_account = portfolio.broker_account
        payloads = BrokerImportService.fetch_live_positions(broker_account)

        imported = []
        remote_ids = set()

        for payload in payloads:
            position = BrokerImportService._upsert_position_from_payload(
                portfolio=portfolio,
                broker_account=broker_account,
                payload=payload,
            )
            imported.append(position)
            if position.broker_position_id:
                remote_ids.add(position.broker_position_id)

        existing_imported_open = portfolio.positions.filter(
            source="IMPORTED",
            status="OPEN",
        )

        for pos in existing_imported_open:
            if pos.broker_position_id and pos.broker_position_id not in remote_ids:
                pos.status = "CLOSED"
                pos.closed_at = timezone.now()
                pos.save(update_fields=["status", "closed_at", "updated_at"])

        remote_cash = BrokerImportService._fetch_remote_cash(broker_account)
        if remote_cash is not None:
            portfolio = PortfolioService.recompute_cash_state(portfolio)
            delta = _d(remote_cash) - _d(portfolio.current_balance)

            if delta != 0:
                PortfolioAccountingService.add_ledger_entry(
                    portfolio=portfolio,
                    entry_type="BROKER_IMPORT",
                    amount=delta,
                    reference_type="BROKER_SYNC",
                    reference_id=str(broker_account.id),
                    description="Ajustement cash suite import broker",
                    metadata={"broker": broker_account.broker},
                )

        PortfolioService.refresh_portfolio_metrics(portfolio)
        portfolio.last_reconciled_at = timezone.now()
        portfolio.save(update_fields=["last_reconciled_at", "updated_at"])

        return imported
