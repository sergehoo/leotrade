from django.contrib import admin

from dashboard.models import KYCProfile


# Register your models here.


@admin.register(KYCProfile)
class KYCProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "status", "full_name", "nationality", "reviewed_by", "updated_at")
    list_filter = ("status", "nationality", "id_document_type")
    search_fields = ("user__email", "full_name", "id_document_number")
    readonly_fields = ("created_at", "updated_at", "reviewed_at")
