from decimal import Decimal
from unittest import mock

import pytest
from django.db import transaction
from django.test import override_settings


@pytest.mark.django_db
def test_outbox_event_rolls_back_with_business_transaction():
    from core.models import OutboxEvent
    from core.outbox import OutboxService

    with pytest.raises(RuntimeError), transaction.atomic():
        OutboxService.enqueue(
            topic="test.rollback.v1",
            aggregate_type="test.Aggregate",
            aggregate_id="1",
            payload={"value": 1},
            nudge=False,
        )
        raise RuntimeError("rollback")

    assert OutboxEvent.objects.count() == 0


@pytest.mark.django_db
def test_outbox_publisher_delivers_and_marks_event_published():
    from core.outbox import OutboxPublisher, OutboxService, _HANDLERS

    handler = mock.Mock()
    event = OutboxService.enqueue(
        topic="test.publish.v1",
        aggregate_type="test.Aggregate",
        aggregate_id="42",
        payload={"value": "ok"},
        nudge=False,
    )

    with mock.patch.dict(_HANDLERS, {"test.publish.v1": handler}):
        result = OutboxPublisher.publish_pending()

    event.refresh_from_db()
    assert result == {"claimed": 1, "published": 1, "retried": 0, "dead": 0}
    assert event.status == "PUBLISHED"
    assert event.attempts == 1
    assert event.published_at is not None
    handler.assert_called_once()
    assert handler.call_args.args[0].event_id == event.event_id


@pytest.mark.django_db
@override_settings(OUTBOX_MAX_ATTEMPTS=1)
def test_outbox_moves_poison_event_to_dead_letter():
    from core.outbox import OutboxPublisher, OutboxService, _HANDLERS

    event = OutboxService.enqueue(
        topic="test.poison.v1",
        aggregate_type="test.Aggregate",
        aggregate_id="9",
        nudge=False,
    )
    handler = mock.Mock(side_effect=ValueError("invalid payload"))

    with mock.patch.dict(_HANDLERS, {"test.poison.v1": handler}):
        result = OutboxPublisher.publish_pending()

    event.refresh_from_db()
    assert result["dead"] == 1
    assert event.status == "DEAD"
    assert "ValueError" in event.last_error


@pytest.mark.django_db
def test_outbox_enqueue_is_idempotent():
    from core.models import OutboxEvent
    from core.outbox import OutboxService

    first = OutboxService.enqueue(
        topic="test.idempotent.v1",
        aggregate_type="test.Aggregate",
        aggregate_id="7",
        idempotency_key="test-event-7",
        nudge=False,
    )
    second = OutboxService.enqueue(
        topic="test.idempotent.v1",
        aggregate_type="test.Aggregate",
        aggregate_id="7",
        idempotency_key="test-event-7",
        nudge=False,
    )

    assert second.pk == first.pk
    assert OutboxEvent.objects.count() == 1


@pytest.mark.django_db
def test_execution_event_creates_durable_realtime_delivery(
    user,
    broker_paper,
    portfolio_paper,
):
    from core.models import OutboxEvent
    from execution.event_topics import ORDER_EVENT
    from execution.models import Order
    from execution.services import ExecutionEventService

    order = Order.objects.create(
        user=user,
        portfolio=portfolio_paper,
        broker_account=broker_paper,
        symbol="R_100",
        side="BUY",
        approved_quantity=Decimal("1"),
        approved_notional=Decimal("10"),
        idempotency_key="outbox-execution-event",
    )

    with mock.patch("core.outbox._nudge_publisher"):
        event = ExecutionEventService.log(
            order,
            "ORDER_CREATED",
            "Created",
            {"amount": Decimal("10")},
        )

    delivery = OutboxEvent.objects.get(
        idempotency_key=f"execution-event:{event.id}:realtime"
    )
    assert delivery.topic == ORDER_EVENT
    assert delivery.payload["user_id"] == user.id
    assert delivery.payload["payload"]["payload"]["amount"] == "10"


@pytest.mark.django_db
def test_notification_dispatch_is_enqueued_durably(user):
    from core.models import OutboxEvent
    from notifications.event_topics import NOTIFICATION_DISPATCH_REQUESTED
    from notifications.services import NotificationService

    with mock.patch("core.outbox._nudge_publisher"):
        notification = NotificationService.notify(
            user,
            "ORDER_CREATED",
            title="Order created",
            message="Test",
            channels=["IN_APP"],
        )

    assert notification is not None
    assert OutboxEvent.objects.filter(
        topic=NOTIFICATION_DISPATCH_REQUESTED,
        aggregate_id=str(notification.id),
        idempotency_key=f"notification:{notification.id}:dispatch",
    ).exists()


@pytest.mark.django_db
def test_duplicate_submit_delivery_calls_broker_once(
    user,
    broker_paper,
    portfolio_paper,
):
    from execution.models import Order
    from execution.tasks import submit_order_to_broker_task

    order = Order.objects.create(
        user=user,
        portfolio=portfolio_paper,
        broker_account=broker_paper,
        symbol="R_100",
        side="BUY",
        approved_quantity=Decimal("1"),
        approved_notional=Decimal("10"),
        requested_price=Decimal("10"),
        idempotency_key="outbox-submit-once",
    )
    adapter = mock.Mock()
    adapter.submit_order.return_value = {
        "broker_order_id": "paper-42",
        "broker_client_order_id": order.idempotency_key,
        "fills": [],
    }

    with mock.patch(
        "execution.adapters.factory.BrokerAdapterFactory.build",
        return_value=adapter,
    ), mock.patch("core.outbox._nudge_publisher"):
        first = submit_order_to_broker_task(order.id)
        second = submit_order_to_broker_task(order.id)

    order.refresh_from_db()
    assert first["ok"] is True
    assert second["skipped"] is True
    assert order.status == "SUBMITTED"
    adapter.submit_order.assert_called_once()
