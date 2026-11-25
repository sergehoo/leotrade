from celery import shared_task
from django.utils import timezone
from datetime import timedelta

from execution.models import IdempotencyKey


@shared_task
def cleanup_old_idempotency_keys_task(days=7):
    threshold = timezone.now() - timedelta(days=days)
    qs = IdempotencyKey.objects.filter(created_at__lt=threshold)
    count = qs.count()
    qs.delete()
    return {"deleted_count": count}