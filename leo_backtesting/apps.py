from django.apps import AppConfig


class LeoBacktestingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "leo_backtesting"

    def ready(self):
        from leo_backtesting import outbox  # noqa: F401
