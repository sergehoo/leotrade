from django.apps import AppConfig


class ExecutionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'execution'

    def ready(self):
        from execution import outbox  # noqa: F401
