from django.contrib import admin

from .models import (
    Notification,
    NotificationDeliveryLog,
    NotificationPreference,
    NotificationTemplate,
)


class DeliveryLogInline(admin.TabularInline):
    model = NotificationDeliveryLog
    extra = 0
    can_delete = False
    readonly_fields = (
        "channel", "provider", "status", "recipient",
        "error_message", "retry_count", "sent_at", "created_at",
    )
    fields = readonly_fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "id", "user", "event_type", "severity", "priority",
        "status", "is_read_display", "created_at",
    )
    list_filter = ("event_type", "severity", "priority", "status", "created_at")
    search_fields = ("title", "message", "user__username", "user__email")
    date_hierarchy = "created_at"
    readonly_fields = (
        "user", "title", "message", "event_type", "severity", "priority",
        "channels_requested", "channels_sent", "status", "payload",
        "read_at", "created_at", "updated_at",
    )
    inlines = [DeliveryLogInline]
    actions = ["resend_notifications"]

    @admin.display(boolean=True, description="Lue")
    def is_read_display(self, obj):
        return obj.is_read

    @admin.action(description="Renvoyer les notifications sélectionnées")
    def resend_notifications(self, request, queryset):
        from notifications.tasks import send_notification_task

        count = 0
        for notification in queryset:
            notification.status = "PENDING"
            notification.save(update_fields=["status", "updated_at"])
            send_notification_task.delay(notification.id)
            count += 1
        self.message_user(request, f"{count} notification(s) re-planifiée(s).")


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = (
        "user", "email_enabled", "in_app_enabled", "sms_enabled",
        "whatsapp_enabled", "preferred_language",
        "quiet_hours_start", "quiet_hours_end",
    )
    list_filter = ("email_enabled", "sms_enabled", "whatsapp_enabled", "preferred_language")
    search_fields = ("user__username", "user__email", "phone_number")


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    list_display = ("event_type", "channel", "language", "is_active", "updated_at")
    list_filter = ("channel", "language", "is_active", "event_type")
    search_fields = ("event_type", "subject", "body")
    list_editable = ("is_active",)


@admin.register(NotificationDeliveryLog)
class NotificationDeliveryLogAdmin(admin.ModelAdmin):
    list_display = (
        "id", "notification", "channel", "provider", "status",
        "recipient", "retry_count", "sent_at", "created_at",
    )
    list_filter = ("channel", "provider", "status", "created_at")
    search_fields = ("recipient", "error_message", "notification__title")
    date_hierarchy = "created_at"
    readonly_fields = (
        "notification", "channel", "provider", "status", "recipient",
        "request_payload", "response_payload", "error_message",
        "sent_at", "retry_count", "created_at", "updated_at",
    )
