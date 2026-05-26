from django.contrib import admin

from leo_backtesting.models import BacktestRun


# Register your models here.
@admin.register(BacktestRun)
class BacktestRunAdmin(admin.ModelAdmin):
    list_display = ("name", "strategy", "start_date", "end_date", "status")
    list_filter = ("status", "strategy")
    search_fields = ("name", "strategy__name")