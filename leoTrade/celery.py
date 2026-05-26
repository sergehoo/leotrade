import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "leoTrade.settings")

app = Celery("leoTrade")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()