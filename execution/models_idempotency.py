from django.db import models
from django.conf import settings


class IdempotencyKey(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="idempotency_keys",
    )
    key = models.CharField(max_length=120, db_index=True)
    endpoint = models.CharField(max_length=255, db_index=True)
    request_hash = models.CharField(max_length=128, db_index=True)
    response_payload = models.JSONField(default=dict, blank=True)
    status_code = models.PositiveIntegerField(default=200)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "endpoint", "key"],
                name="execution_unique_user_endpoint_idem_key",
            ),
        ]

    def __str__(self):
        return f"{self.user_id}:{self.endpoint}:{self.key}"
