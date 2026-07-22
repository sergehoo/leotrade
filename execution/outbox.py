from core.outbox import OutboxDeliveryError, register_outbox_handler
from core.realtime import RealtimeBroadcastService
from execution.event_topics import (
    DASHBOARD_UPDATE,
    NOTIFICATION_UPDATE,
    ORDER_EVENT,
    ORDER_SUBMIT_REQUESTED,
    ORDER_UPDATE,
    PORTFOLIO_RECONCILE_REQUESTED,
    PORTFOLIO_UPDATE,
)


def _realtime_payload(event):
    payload = dict(event.payload.get("payload") or {})
    payload.setdefault("outbox_event_id", str(event.event_id))
    return payload


def _require_delivery(delivered: bool, destination: str) -> None:
    if not delivered:
        raise OutboxDeliveryError(f"Realtime delivery failed for {destination}")


@register_outbox_handler(ORDER_EVENT)
@register_outbox_handler(ORDER_UPDATE)
def publish_order_update(event):
    _require_delivery(
        RealtimeBroadcastService.broadcast_order_update(
            user_id=int(event.payload["user_id"]),
            payload=_realtime_payload(event),
        ),
        ORDER_UPDATE,
    )


@register_outbox_handler(DASHBOARD_UPDATE)
def publish_dashboard_update(event):
    _require_delivery(
        RealtimeBroadcastService.broadcast_dashboard_update(
            user_id=int(event.payload["user_id"]),
            payload=_realtime_payload(event),
        ),
        DASHBOARD_UPDATE,
    )


@register_outbox_handler(PORTFOLIO_UPDATE)
def publish_portfolio_update(event):
    _require_delivery(
        RealtimeBroadcastService.broadcast_portfolio_update(
            portfolio_id=int(event.payload["portfolio_id"]),
            payload=_realtime_payload(event),
        ),
        PORTFOLIO_UPDATE,
    )


@register_outbox_handler(NOTIFICATION_UPDATE)
def publish_notification_update(event):
    _require_delivery(
        RealtimeBroadcastService.broadcast_notification(
            user_id=int(event.payload["user_id"]),
            payload=_realtime_payload(event),
        ),
        NOTIFICATION_UPDATE,
    )


@register_outbox_handler(ORDER_SUBMIT_REQUESTED)
def submit_order(event):
    from execution.tasks import submit_order_to_broker_task

    submit_order_to_broker_task.apply_async(
        args=(int(event.payload["order_id"]),),
        task_id=f"outbox-{event.event_id}",
    )


@register_outbox_handler(PORTFOLIO_RECONCILE_REQUESTED)
def reconcile_portfolio(event):
    from execution.tasks import reconcile_portfolio_orders_task

    reconcile_portfolio_orders_task.apply_async(
        args=(int(event.payload["portfolio_id"]),),
        countdown=int(event.payload.get("countdown", 0)),
        task_id=f"outbox-{event.event_id}",
    )
