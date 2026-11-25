from core.outbox import register_outbox_handler
from notifications.event_topics import NOTIFICATION_DISPATCH_REQUESTED


@register_outbox_handler(NOTIFICATION_DISPATCH_REQUESTED)
def dispatch_notification(event):
    from notifications.tasks import send_notification_task

    send_notification_task.apply_async(
        args=(int(event.payload["notification_id"]),),
        task_id=f"outbox-{event.event_id}",
    )
