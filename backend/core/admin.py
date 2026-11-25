from django.contrib import admin
from django.utils import timezone

from core.models import OutboxEvent


@admin.register(OutboxEvent)
class OutboxEventAdmin(admin.ModelAdmin):
    list_display = (
        "event_id",
        "topic",
        "aggregate_type",
        "aggregate_id",
        "status",
        "attempts",
        "available_at",
        "published_at",
    )
    list_filter = ("status", "topic")
    search_fields = (
        "event_id",
        "idempotency_key",
        "aggregate_type",
        "aggregate_id",
        "last_error",
    )
    readonly_fields = (
        "event_id",
        "attempts",
        "locked_at",
        "published_at",
        "last_error",
        "created_at",
        "updated_at",
    )
    actions = ("retry_dead_events",)

    @admin.action(description="Retry selected dead-letter events")
    def retry_dead_events(self, request, queryset):
        count = queryset.filter(status="DEAD").update(
            status="PENDING",
            attempts=0,
            available_at=timezone.now(),
            locked_at=None,
            last_error="",
            updated_at=timezone.now(),
        )
        self.message_user(request, f"{count} event(s) scheduled for retry.")

# Register your models here.
