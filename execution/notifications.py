from __future__ import annotations

from core.realtime import RealtimeBroadcastService


class TradingNotificationService:
    @staticmethod
    def notify_order_created(order):
        RealtimeBroadcastService.broadcast_order_update(
            user_id=order.user_id,
            payload={
                "kind": "order_created",
                "order_id": order.id,
                "symbol": order.symbol,
                "status": order.status,
                "side": order.side,
                "approved_quantity": str(order.approved_quantity),
                "approved_notional": str(order.approved_notional),
            },
        )

    @staticmethod
    def notify_order_submitted(order):
        RealtimeBroadcastService.broadcast_order_update(
            user_id=order.user_id,
            payload={
                "kind": "order_submitted",
                "order_id": order.id,
                "broker_order_id": order.broker_order_id,
                "symbol": order.symbol,
                "status": order.status,
            },
        )

    @staticmethod
    def notify_order_filled(order):
        RealtimeBroadcastService.broadcast_order_update(
            user_id=order.user_id,
            payload={
                "kind": "order_filled",
                "order_id": order.id,
                "symbol": order.symbol,
                "status": order.status,
                "filled_quantity": str(order.filled_quantity),
                "average_fill_price": str(order.average_fill_price),
                "filled_notional": str(order.filled_notional),
            },
        )

    @staticmethod
    def notify_order_cancelled(order):
        RealtimeBroadcastService.broadcast_order_update(
            user_id=order.user_id,
            payload={
                "kind": "order_cancelled",
                "order_id": order.id,
                "symbol": order.symbol,
                "status": order.status,
            },
        )

    @staticmethod
    def notify_error(user_id: int, message: str, payload: dict | None = None):
        RealtimeBroadcastService.broadcast_notification(
            user_id=user_id,
            payload={
                "kind": "error",
                "message": message,
                "payload": payload or {},
            },
        )

    @staticmethod
    def notify_success(user_id: int, message: str, payload: dict | None = None):
        RealtimeBroadcastService.broadcast_notification(
            user_id=user_id,
            payload={
                "kind": "success",
                "message": message,
                "payload": payload or {},
            },
        )