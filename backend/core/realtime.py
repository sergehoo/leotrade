from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


logger = logging.getLogger(__name__)


# Version du protocole de payload temps réel.
# Les clients (leo_websocket.js) ignorent les payloads de version supérieure
# à celle qu'ils connaissent, ce qui permet de faire évoluer le schéma sans
# casser les onglets ouverts depuis longtemps.
REALTIME_PROTOCOL_VERSION = 1


class RealtimeBroadcastService:
    @staticmethod
    def _json_safe(value):
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, UUID):
            return str(value)
        return value

    @classmethod
    def _normalize_payload(cls, payload):
        if payload is None:
            return {}
        if not isinstance(payload, dict):
            return {"value": cls._json_safe(payload)}

        normalized = {}
        for key, value in payload.items():
            if isinstance(value, dict):
                normalized[key] = cls._normalize_payload(value)
            elif isinstance(value, list):
                normalized[key] = [
                    cls._normalize_payload(item) if isinstance(item, dict) else cls._json_safe(item)
                    for item in value
                ]
            else:
                normalized[key] = cls._json_safe(value)
        return normalized

    @classmethod
    def _send(cls, group_name: str, event_type: str, payload: dict | None = None) -> bool:
        """
        Send to channel layer.

        Note: callers inside an open DB transaction should use
        ``broadcast_after_commit`` (see below) so consumers never see
        events for state that gets rolled back.
        """
        channel_layer = get_channel_layer()
        if not channel_layer:
            logger.warning(
                "Realtime broadcast skipped: no channel layer available. group=%s event=%s",
                group_name,
                event_type,
            )
            return False

        safe_payload = cls._normalize_payload(payload)

        # On force toujours le champ "version" dans le payload pour permettre
        # aux clients front d'ignorer les schémas trop récents qu'ils ne
        # comprendraient pas. Si le caller a déjà fourni une version (ex pour
        # un payload d'événement spécifique), on ne l'écrase pas.
        if isinstance(safe_payload, dict):
            safe_payload.setdefault("version", REALTIME_PROTOCOL_VERSION)

        try:
            async_to_sync(channel_layer.group_send)(
                group_name,
                {
                    # NOTE : Channels convertit "broadcast.message" → handler
                    # "broadcast_message". On garde la convention "." pour
                    # rester compatible avec l'existant.
                    "type": "broadcast.message",
                    "event_type": event_type,
                    "payload": safe_payload,
                },
            )
            logger.debug(
                "Realtime broadcast sent: group=%s event=%s payload=%s",
                group_name,
                event_type,
                safe_payload,
            )
            return True
        except Exception:
            logger.exception(
                "Realtime broadcast failed: group=%s event=%s",
                group_name,
                event_type,
            )
            return False

    @classmethod
    def broadcast_after_commit(
        cls,
        group_name: str,
        event_type: str,
        payload: dict | None = None,
    ) -> None:
        """
        Schedule a broadcast that fires only when the surrounding DB
        transaction commits. Falls back to immediate send when called
        outside a transaction.
        """
        from django.db import transaction
        from django.db.transaction import TransactionManagementError

        def _do_send():
            cls._send(group_name, event_type, payload)

        try:
            transaction.on_commit(_do_send)
        except TransactionManagementError:
            _do_send()

    @staticmethod
    def portfolio_group(portfolio_id: int) -> str:
        return f"portfolio_{portfolio_id}"

    @staticmethod
    def user_orders_group(user_id: int) -> str:
        return f"user_orders_{user_id}"

    @staticmethod
    def user_notifications_group(user_id: int) -> str:
        return f"user_notifications_{user_id}"

    @staticmethod
    def dashboard_group(user_id: int) -> str:
        return f"user_dashboard_{user_id}"

    @staticmethod
    def user_ai_group(user_id: int) -> str:
        return f"user_ai_{user_id}"

    @classmethod
    def broadcast_portfolio_update(cls, portfolio_id: int, payload: dict | None = None) -> bool:
        return cls._send(
            cls.portfolio_group(portfolio_id),
            "portfolio.update",
            payload,
        )

    @classmethod
    def broadcast_order_update(cls, user_id: int, payload: dict | None = None) -> bool:
        return cls._send(
            cls.user_orders_group(user_id),
            "order.update",
            payload,
        )

    @classmethod
    def broadcast_notification(cls, user_id: int, payload: dict | None = None) -> bool:
        return cls._send(
            cls.user_notifications_group(user_id),
            "notification.created",
            payload,
        )

    @classmethod
    def broadcast_dashboard_update(cls, user_id: int, payload: dict | None = None) -> bool:
        return cls._send(
            cls.dashboard_group(user_id),
            "dashboard.update",
            payload,
        )

    @classmethod
    def broadcast_ai_update(cls, user_id: int, payload: dict | None = None) -> bool:
        return cls._send(
            cls.user_ai_group(user_id),
            "ai.update",
            payload,
        )

    # =========================================================================
    # Market data — candles & ticks live
    # =========================================================================

    @staticmethod
    def candles_group(asset_id: int, timeframe_code: str) -> str:
        return f"candles_{asset_id}_{timeframe_code}"

    @classmethod
    def broadcast_candle(
        cls,
        *,
        asset_id: int,
        timeframe_code: str,
        candle: dict,
    ) -> bool:
        """
        Pousse une bougie (nouvelle ou updated) aux clients abonnés à
        ``candles_{asset_id}_{timeframe_code}``. À appeler après chaque
        ``Candle.objects.update_or_create()`` réussie.

        ``candle`` doit être un dict JSON-safe :
            {"open_time": "2026-01-01T00:00:00Z", "open": "1.10",
             "high": "1.12", "low": "1.09", "close": "1.115", "volume": "1234"}
        """
        return cls._send(
            cls.candles_group(asset_id, timeframe_code),
            "candle.update",
            {"candle": candle, "asset_id": asset_id, "timeframe": timeframe_code},
        )

    @classmethod
    def broadcast_position_update(
        cls,
        *,
        portfolio_id: int,
        position: dict,
    ) -> bool:
        """
        Pousse l'état d'une position au groupe portfolio_{id}.
        À appeler après chaque modification de Position (ouverture, mark-to-market,
        fermeture totale/partielle).
        """
        return cls._send(
            cls.portfolio_group(portfolio_id),
            "position.update",
            {"position": position},
        )