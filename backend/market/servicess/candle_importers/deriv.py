from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

from brokers.models import BrokerAccount
from brokers.services.deriv import DerivClient, DerivClientError
from market.models import Asset, Candle, Timeframe


logger = logging.getLogger(__name__)


DERIV_GRANULARITY_MAP = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
    "1w": 604800,
    "1M": 2592000,
}


class DerivCandleImporter:
    @staticmethod
    def _to_dt(epoch_seconds: int) -> datetime:
        return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)

    @classmethod
    def _resolve_deriv_broker(cls) -> BrokerAccount:
        broker = (
            BrokerAccount.objects
            .filter(broker="DERIV", is_active=True)
            .order_by("-is_default", "id")
            .first()
        )
        if not broker:
            raise RuntimeError("Aucun BrokerAccount Deriv actif trouvé.")
        return broker

    @classmethod
    @transaction.atomic
    def import_candles(cls, asset: Asset, timeframe: Timeframe, count: int = 300) -> dict:
        if asset.exchange != "DERIV":
            raise ValueError(f"L'asset {asset.symbol} n'est pas de type DERIV.")

        granularity = DERIV_GRANULARITY_MAP.get(timeframe.code)
        if not granularity:
            raise ValueError(f"Timeframe non supporté pour Deriv: {timeframe.code}")

        broker = cls._resolve_deriv_broker()
        client = DerivClient(token=broker.deriv_token, app_id=broker.deriv_app_id)

        created = 0
        updated = 0

        channel_layer = get_channel_layer()
        group_name = f"candles_{asset.id}_{timeframe.code}"

        try:
            accounts_resp = client.list_options_accounts()
            accounts = accounts_resp.get("data", [])
            if not accounts:
                logger.warning("Aucun compte options Deriv disponible pour asset=%s", asset.symbol)
                return {
                    "status": "skipped",
                    "reason": "no_options_account",
                    "asset": asset.symbol,
                    "timeframe": timeframe.code,
                    "rows": 0,
                    "created": 0,
                    "updated": 0,
                }

            preferred_type = (broker.deriv_account_type or "demo").lower()
            selected = None

            for acc in accounts:
                if str(acc.get("account_type", "")).lower() == preferred_type:
                    selected = acc
                    break

            if not selected:
                selected = accounts[0]

            account_id = selected.get("account_id")
            if not account_id:
                logger.warning("Compte Deriv invalide pour asset=%s selected=%s", asset.symbol, selected)
                return {
                    "status": "skipped",
                    "reason": "invalid_account",
                    "asset": asset.symbol,
                    "timeframe": timeframe.code,
                    "rows": 0,
                    "created": 0,
                    "updated": 0,
                }

            ws_url = client.get_otp_ws_url_with_retry(account_id, retries=3, sleep_seconds=2.0)
            client.connect_with_otp_url(ws_url)

            try:
                resp = client.candles(
                    symbol=asset.symbol,
                    granularity=granularity,
                    count=count,
                )
            except DerivClientError as exc:
                if "InvalidSymbol" in str(exc):
                    logger.warning(
                        "Symbole Deriv invalide ignoré: asset=%s timeframe=%s",
                        asset.symbol,
                        timeframe.code,
                    )
                    return {
                        "status": "skipped",
                        "reason": "invalid_symbol",
                        "asset": asset.symbol,
                        "timeframe": timeframe.code,
                        "rows": 0,
                        "created": 0,
                        "updated": 0,
                    }
                raise

            candles = resp.get("candles", []) or []

            for row in candles:
                epoch = int(row["epoch"])
                open_time = cls._to_dt(epoch)
                close_time = cls._to_dt(epoch + granularity)

                defaults = {
                    "close_time": close_time,
                    "open": Decimal(str(row["open"])),
                    "high": Decimal(str(row["high"])),
                    "low": Decimal(str(row["low"])),
                    "close": Decimal(str(row["close"])),
                    "volume": Decimal(str(row.get("volume", 0))),
                    "trade_count": int(row.get("trade_count", 0) or 0),
                }

                candle_obj, was_created = Candle.objects.update_or_create(
                    asset=asset,
                    timeframe=timeframe,
                    open_time=open_time,
                    defaults=defaults,
                )

                if was_created:
                    created += 1
                else:
                    updated += 1

                payload = {
                    "type": "candle.update",
                    "asset_id": asset.id,
                    "symbol": asset.symbol,
                    "timeframe": timeframe.code,
                    "candle": {
                        "id": candle_obj.id,
                        "open_time": int(open_time.timestamp()) if open_time else None,
                        "open_time_iso": open_time.isoformat() if open_time else None,
                        "close_time": int(close_time.timestamp()) if close_time else None,
                        "close_time_iso": close_time.isoformat() if close_time else None,
                        "open": float(defaults["open"]),
                        "high": float(defaults["high"]),
                        "low": float(defaults["low"]),
                        "close": float(defaults["close"]),
                        "volume": float(defaults["volume"]),
                        "trade_count": int(defaults["trade_count"]),
                        "timeframe": timeframe.code,
                    },
                    "is_new": was_created,
                }

                async_to_sync(channel_layer.group_send)(
                    group_name,
                    {
                        "type": "candle_update",
                        "data": payload,
                    }
                )

            return {
                "status": "ok",
                "asset": asset.symbol,
                "timeframe": timeframe.code,
                "rows": len(candles),
                "created": created,
                "updated": updated,
            }

        except DerivClientError as exc:
            logger.error(
                "Deriv candle import failed asset=%s timeframe=%s error=%s",
                asset.symbol,
                timeframe.code,
                exc,
            )
            return {
                "status": "failed",
                "reason": str(exc),
                "asset": asset.symbol,
                "timeframe": timeframe.code,
                "rows": 0,
                "created": created,
                "updated": updated,
            }
        finally:
            client.close()