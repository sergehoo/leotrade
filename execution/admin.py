from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import Order, ExecutionFill, ExecutionEvent, BrokerSyncLog


class ExecutionFillInline(admin.TabularInline):
    model = ExecutionFill
    extra = 0
    readonly_fields = ("broker_fill_id", "quantity", "price", "notional", "fee", "fill_time", "metadata")


class ExecutionEventInline(admin.TabularInline):
    model = ExecutionEvent
    extra = 0
    readonly_fields = ("event_type", "message", "payload", "created_at")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id", "user", "portfolio", "broker_account", "symbol",
        "side", "order_type", "mode", "status",
        "approved_quantity", "filled_quantity", "broker_order_id",
        "submitted_at", "filled_at",
    )
    list_filter = ("mode", "status", "side", "order_type", "source", "broker_account__broker")
    search_fields = ("symbol", "broker_order_id", "broker_client_order_id", "idempotency_key", "user__email")
    readonly_fields = ("created_at", "updated_at", "submitted_at", "filled_at", "cancelled_at", "rejected_at", "expired_at")
    inlines = [ExecutionFillInline, ExecutionEventInline]


@admin.register(ExecutionFill)
class ExecutionFillAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "broker_fill_id", "quantity", "price", "notional", "fee", "fill_time")
    search_fields = ("broker_fill_id", "order__broker_order_id", "order__symbol")
    list_filter = ("fee_currency",)


@admin.register(ExecutionEvent)
class ExecutionEventAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "event_type", "created_at", "created_by_system")
    search_fields = ("order__symbol", "order__broker_order_id", "message")
    list_filter = ("event_type", "created_by_system")


@admin.register(BrokerSyncLog)
class BrokerSyncLogAdmin(admin.ModelAdmin):
    list_display = ("id", "broker_account", "portfolio", "sync_type", "status", "processed_count", "error_count", "started_at", "finished_at")
    list_filter = ("sync_type", "status", "broker_account__broker")
    search_fields = ("broker_account__name", "portfolio__name", "message")