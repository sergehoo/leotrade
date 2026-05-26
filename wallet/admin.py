from django.contrib import admin

from wallet.models import WithdrawalRequest, ProviderWebhookEvent, WalletTransaction, PaymentMethod, Wallet


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("user", "currency", "available_balance", "locked_balance", "total_deposited", "total_withdrawn", "is_active")
    search_fields = ("user__username", "user__email")
    list_filter = ("currency", "is_active")


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "method_type", "brand", "last4", "is_default", "is_active", "created_at")
    list_filter = ("provider", "method_type", "is_default", "is_active")
    search_fields = ("user__username", "user__email", "last4", "provider_customer_id", "provider_payment_method_id")


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ("wallet", "tx_type", "status", "amount", "currency", "provider", "provider_reference", "created_at")
    list_filter = ("tx_type", "status", "provider", "currency")
    search_fields = ("wallet__user__email", "wallet__user__username", "provider_reference", "provider_session_id")
    readonly_fields = ("created_at", "updated_at", "processed_at")


@admin.register(WithdrawalRequest)
class WithdrawalRequestAdmin(admin.ModelAdmin):
    list_display = ("wallet", "amount", "currency", "destination_type", "status", "provider", "created_at")
    list_filter = ("status", "destination_type", "provider", "currency")
    search_fields = ("wallet__user__email", "wallet__user__username", "provider_reference", "destination_masked")
    readonly_fields = ("created_at", "updated_at", "reviewed_at", "paid_at")


@admin.register(ProviderWebhookEvent)
class ProviderWebhookEventAdmin(admin.ModelAdmin):
    list_display = ("provider", "event_id", "event_type", "processed", "created_at")
    list_filter = ("provider", "processed")
    search_fields = ("event_id", "event_type")
