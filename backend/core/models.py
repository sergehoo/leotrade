from uuid import uuid4

from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class OutboxEvent(TimeStampedModel):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("PROCESSING", "Processing"),
        ("PUBLISHED", "Published"),
        ("DEAD", "Dead Letter"),
    ]

    event_id = models.UUIDField(default=uuid4, unique=True, editable=False)
    topic = models.CharField(max_length=120, db_index=True)
    aggregate_type = models.CharField(max_length=80, db_index=True)
    aggregate_id = models.CharField(max_length=120, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default="PENDING",
        db_index=True,
    )
    attempts = models.PositiveIntegerField(default=0)
    available_at = models.DateTimeField(default=timezone.now, db_index=True)
    locked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_error = models.TextField(blank=True, default="")
    idempotency_key = models.CharField(
        max_length=180,
        unique=True,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["status", "available_at"]),
            models.Index(fields=["topic", "status"]),
            models.Index(fields=["aggregate_type", "aggregate_id"]),
        ]

    def __str__(self):
        return f"{self.topic} [{self.status}] {self.event_id}"
