import os
from celery import Celery

default_settings = (
    "leoTrade.settings.prod"
    if os.environ.get("DJANGO_ENV") == "prod"
    else "leoTrade.settings.dev"
)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", default_settings)

app = Celery("leoTrade")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
