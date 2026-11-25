"""
Modèles du module notifications.

- Notification          : la notification elle-même (statut, canaux, lecture)
- NotificationPreference: préférences par utilisateur (canaux, catégories,
                          quiet hours, numéros)
- NotificationTemplate  : gabarits par événement × canal × langue
- NotificationDeliveryLog: journal de chaque tentative d'envoi par canal

Règle de fond : aucune donnée sensible (clés API broker, tokens) ne doit
jamais transiter dans payload / request_payload — les intégrations n'y
mettent que des identifiants et des montants.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from .events import Channel, EVENT_CHOICES, Priority, Severity


class Notification(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),        # créée, dispatch Celery en attente
        ("SENT", "Sent"),              # au moins un canal délivré
        ("PARTIAL", "Partial"),        # certains canaux délivrés, d'autres en échec
        ("FAILED", "Failed"),          # aucun canal délivré
        ("SUPPRESSED", "Suppressed"),  # filtrée (préférences, quiet hours, rate limit)
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )

    title = models.CharField(max_length=200)
    message = models.TextField()
    event_type = models.CharField(max_length=50, choices=EVENT_CHOICES, db_index=True)
    severity = models.CharField(max_length=10, choices=Severity.CHOICES, default=Severity.INFO, db_index=True)
    priority = models.CharField(max_length=10, choices=Priority.CHOICES, default=Priority.NORMAL, db_index=True)

    channels_requested = models.JSONField(default=list, blank=True)
    channels_sent = models.JSONField(default=list, blank=True)

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="PENDING", db_index=True)
    payload = models.JSONField(default=dict, blank=True)

    read_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "read_at"]),
            models.Index(fields=["user", "event_type", "created_at"]),
            models.Index(fields=["user", "status"]),
        ]

    def __str__(self):
        return f"[{self.severity}] {self.title} → user={self.user_id}"

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    def mark_read(self):
        if self.read_at is None:
            self.read_at = timezone.now()
            self.save(update_fields=["read_at", "updated_at"])


class NotificationPreference(models.Model):
    LANGUAGE_CHOICES = [("fr", "Français"), ("en", "English")]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preference",
    )

    # Canaux
    email_enabled = models.BooleanField(default=True)
    in_app_enabled = models.BooleanField(default=True)
    sms_enabled = models.BooleanField(default=False)
    whatsapp_enabled = models.BooleanField(default=False)

    # Catégories
    trade_events_enabled = models.BooleanField(default=True)
    risk_events_enabled = models.BooleanField(default=True)
    broker_events_enabled = models.BooleanField(default=True)
    ai_events_enabled = models.BooleanField(default=True)
    security_events_enabled = models.BooleanField(default=True)
    reports_enabled = models.BooleanField(default=True)

    # Quiet hours (heure locale du serveur) — ignorées par les événements critiques
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)

    preferred_language = models.CharField(max_length=5, choices=LANGUAGE_CHOICES, default="fr")
    phone_number = models.CharField(max_length=30, blank=True)
    whatsapp_number = models.CharField(max_length=30, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Préférence de notification"

    def __str__(self):
        return f"Préférences notifications de {self.user}"

    def channel_allowed(self, channel: str) -> bool:
        return {
            Channel.EMAIL: self.email_enabled,
            Channel.IN_APP: self.in_app_enabled,
            Channel.SMS: self.sms_enabled and bool(self.phone_number),
            Channel.WHATSAPP: self.whatsapp_enabled and bool(self.whatsapp_number or self.phone_number),
        }.get(channel, False)

    def in_quiet_hours(self, now=None) -> bool:
        if not self.quiet_hours_start or not self.quiet_hours_end:
            return False
        now_t = (now or timezone.localtime()).time()
        start, end = self.quiet_hours_start, self.quiet_hours_end
        if start <= end:
            return start <= now_t < end
        # Fenêtre qui chevauche minuit (ex. 22:00 → 07:00)
        return now_t >= start or now_t < end


class NotificationTemplate(models.Model):
    event_type = models.CharField(max_length=50, choices=EVENT_CHOICES, db_index=True)
    channel = models.CharField(max_length=10, choices=Channel.CHOICES, db_index=True)
    language = models.CharField(max_length=5, default="fr", db_index=True)

    subject = models.CharField(
        max_length=200, blank=True,
        help_text="Sujet (email) / première ligne (SMS, WhatsApp). Syntaxe template Django.",
    )
    body = models.TextField(
        help_text="Corps du message. Syntaxe template Django ({{ variable }}).",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    variables = models.JSONField(
        default=list, blank=True,
        help_text="Liste documentaire des variables attendues dans le contexte.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("event_type", "channel", "language")]
        ordering = ["event_type", "channel", "language"]

    def __str__(self):
        return f"{self.event_type} / {self.channel} / {self.language}"


class NotificationDeliveryLog(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("SENT", "Sent"),
        ("FAILED", "Failed"),
        ("SKIPPED", "Skipped"),      # canal filtré (préférences, quiet hours…)
        ("RETRYING", "Retrying"),
    ]

    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        related_name="delivery_logs",
    )
    channel = models.CharField(max_length=10, choices=Channel.CHOICES, db_index=True)
    provider = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="PENDING", db_index=True)
    recipient = models.CharField(max_length=255, blank=True)

    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)

    sent_at = models.DateTimeField(null=True, blank=True)
    retry_count = models.PositiveSmallIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "retry_count"]),
            models.Index(fields=["notification", "channel"]),
        ]

    def __str__(self):
        return f"{self.notification_id} → {self.channel} [{self.status}]"
