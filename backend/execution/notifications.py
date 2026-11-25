from __future__ import annotations

from core.outbox import OutboxService
from execution.event_topics import NOTIFICATION_UPDATE, ORDER_UPDATE
from notifications.shortcuts import notify as _notify


def _order_payload(order) -> dict:
    return {
        "order_id": order.id,
        "symbol": order.symbol,
        "side": order.side,
        "mode": order.mode,
        "status": order.status,
        "quantity": str(order.approved_quantity),
        "price": str(order.average_fill_price or 0),
    }


class TradingNotificationService:
    @staticmethod
    def notify_order_created(order):
        _notify(
            order.user, "ORDER_CREATED",
            title=f"Ordre créé : {order.side} {order.symbol}",
            message=(
                f"{'⚠ MODE LIVE — argent réel. ' if order.mode == 'LIVE' else ''}"
                f"Ordre {order.side} {order.symbol} créé "
                f"(qté {order.approved_quantity})."
            ),
            payload=_order_payload(order),
        )
        OutboxService.enqueue(
            topic=ORDER_UPDATE,
            aggregate_type="execution.Order",
            aggregate_id=order.id,
            payload={
                "user_id": order.user_id,
                "payload": {
                    "kind": "order_created",
                    "order_id": order.id,
                    "symbol": order.symbol,
                    "status": order.status,
                    "side": order.side,
                    "approved_quantity": str(order.approved_quantity),
                    "approved_notional": str(order.approved_notional),
                },
            },
            idempotency_key=f"order:{order.id}:realtime-created",
        )

    @staticmethod
    def notify_order_submitted(order):
        _notify(
            order.user, "ORDER_SUBMITTED",
            title=f"Ordre soumis au broker : {order.side} {order.symbol}",
            message=(
                f"{'⚠ MODE LIVE — argent réel. ' if order.mode == 'LIVE' else ''}"
                f"Ordre {order.side} {order.symbol} transmis au broker "
                f"(réf. {order.broker_order_id or 'en attente'})."
            ),
            payload=_order_payload(order),
        )
        OutboxService.enqueue(
            topic=ORDER_UPDATE,
            aggregate_type="execution.Order",
            aggregate_id=order.id,
            payload={
                "user_id": order.user_id,
                "payload": {
                    "kind": "order_submitted",
                    "order_id": order.id,
                    "broker_order_id": order.broker_order_id,
                    "symbol": order.symbol,
                    "status": order.status,
                },
            },
            idempotency_key=f"order:{order.id}:realtime-submitted",
        )

    @staticmethod
    def notify_order_filled(order):
        _notify(
            order.user, "ORDER_FILLED",
            title=f"Ordre exécuté : {order.side} {order.symbol}",
            message=(
                f"{'⚠ MODE LIVE — argent réel. ' if order.mode == 'LIVE' else ''}"
                f"{order.filled_quantity} exécuté(s) à {order.average_fill_price} "
                f"(notional {order.filled_notional})."
            ),
            payload=_order_payload(order),
        )
        OutboxService.enqueue(
            topic=ORDER_UPDATE,
            aggregate_type="execution.Order",
            aggregate_id=order.id,
            payload={
                "user_id": order.user_id,
                "payload": {
                    "kind": "order_filled",
                    "order_id": order.id,
                    "symbol": order.symbol,
                    "status": order.status,
                    "filled_quantity": str(order.filled_quantity),
                    "average_fill_price": str(order.average_fill_price),
                    "filled_notional": str(order.filled_notional),
                },
            },
            idempotency_key=f"order:{order.id}:realtime-filled",
        )

    @staticmethod
    def notify_order_cancelled(order):
        _notify(
            order.user, "ORDER_CANCELLED",
            title=f"Ordre annulé : {order.side} {order.symbol}",
            message=f"L'ordre {order.side} {order.symbol} a été annulé.",
            payload=_order_payload(order),
        )
        OutboxService.enqueue(
            topic=ORDER_UPDATE,
            aggregate_type="execution.Order",
            aggregate_id=order.id,
            payload={
                "user_id": order.user_id,
                "payload": {
                    "kind": "order_cancelled",
                    "order_id": order.id,
                    "symbol": order.symbol,
                    "status": order.status,
                },
            },
            idempotency_key=f"order:{order.id}:realtime-cancelled",
        )

    @staticmethod
    def notify_error(user_id: int, message: str, payload: dict | None = None):
        OutboxService.enqueue(
            topic=NOTIFICATION_UPDATE,
            aggregate_type="auth.User",
            aggregate_id=user_id,
            payload={
                "user_id": user_id,
                "payload": {
                    "kind": "error",
                    "message": message,
                    "payload": payload or {},
                },
            },
        )

    @staticmethod
    def notify_success(user_id: int, message: str, payload: dict | None = None):
        OutboxService.enqueue(
            topic=NOTIFICATION_UPDATE,
            aggregate_type="auth.User",
            aggregate_id=user_id,
            payload={
                "user_id": user_id,
                "payload": {
                    "kind": "success",
                    "message": message,
                    "payload": payload or {},
                },
            },
        )
