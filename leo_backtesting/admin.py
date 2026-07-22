from django.contrib import admin

from leo_backtesting.models import BacktestRun


# Register your models here.
@admin.register(BacktestRun)
class BacktestRunAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "requested_by",
        "strategy",
        "start_date",
        "end_date",
        "data_points",
        "status",
    )
    list_filter = ("status", "strategy")
    search_fields = ("name", "strategy__name", "requested_by__username")
    readonly_fields = (
        "metrics",
        "equity_curve",
        "trades_log",
        "data_checksum",
        "worker_task_id",
        "started_at",
        "completed_at",
        "failure_message",
    )
