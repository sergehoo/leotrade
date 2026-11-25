from django.contrib import admin
from .models import BrokerAccount, BrokerCredential


@admin.register(BrokerAccount)
class BrokerAccountAdmin(admin.ModelAdmin):
    list_display = (
        "id", "user", "name", "broker", "mode",
        "status", "is_active", "is_default",
        "last_connection_status", "last_connected_at",
    )
    list_filter = ("broker", "mode", "status", "is_active", "is_default")
    search_fields = ("name", "user__email", "login", "server")
    readonly_fields = ("created_at", "updated_at", "last_connected_at")


@admin.register(BrokerCredential)
class BrokerCredentialAdmin(admin.ModelAdmin):
    list_display = ("id", "broker_account", "secret_type", "is_active", "key_version", "rotated_at")
    list_filter = ("secret_type", "is_active")
    search_fields = ("broker_account__name", "broker_account__user__email")
    readonly_fields = ("created_at", "updated_at")
    exclude = ("secret_value_encrypted",)