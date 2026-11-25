from rest_framework import serializers

from .models import Notification, NotificationPreference


class NotificationSerializer(serializers.ModelSerializer):
    is_read = serializers.BooleanField(read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id", "title", "message", "event_type", "severity", "priority",
            "channels_requested", "channels_sent", "status", "payload",
            "is_read", "read_at", "created_at",
        ]
        read_only_fields = fields


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = [
            "email_enabled", "in_app_enabled", "sms_enabled", "whatsapp_enabled",
            "trade_events_enabled", "risk_events_enabled", "broker_events_enabled",
            "ai_events_enabled", "security_events_enabled", "reports_enabled",
            "quiet_hours_start", "quiet_hours_end",
            "preferred_language", "phone_number", "whatsapp_number",
        ]
