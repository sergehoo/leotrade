from rest_framework import serializers

from .models import AssistantConversation, AssistantMessage


class AssistantMessageSerializer(serializers.ModelSerializer):
    # Noms alignés sur le cahier des charges (compat app mobile Flutter)
    tokens_input = serializers.IntegerField(source="tokens_in", read_only=True)
    tokens_output = serializers.IntegerField(source="tokens_out", read_only=True)
    model_used = serializers.CharField(source="model_name", read_only=True)
    payload = serializers.JSONField(source="context_snapshot", read_only=True)
    actions = serializers.SerializerMethodField()

    class Meta:
        model = AssistantMessage
        fields = [
            "id", "role", "content", "status", "error_message",
            "tokens_input", "tokens_output", "model_used", "provider",
            "latency_ms", "payload", "actions", "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_actions(self, obj):
        return [
            {
                "id": a.id, "type": a.action_type, "params": a.parameters,
                "status": a.status, "rationale": a.rationale,
            }
            for a in obj.actions.all()
        ]


class AssistantConversationSerializer(serializers.ModelSerializer):
    context_label = serializers.CharField(read_only=True)
    message_count = serializers.IntegerField(read_only=True, default=0)
    last_message_preview = serializers.SerializerMethodField()

    class Meta:
        model = AssistantConversation
        fields = [
            "id", "title", "context_type", "context_id", "context_label",
            "page_context", "is_active", "archived",
            "message_count", "last_message_preview",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "context_label", "message_count", "last_message_preview",
            "created_at", "updated_at",
        ]

    def get_last_message_preview(self, obj):
        last = getattr(obj, "_last_message", None)
        if last is None:
            last = obj.messages.order_by("-created_at").first()
        return (last.content[:140] if last else "")


class AssistantConversationDetailSerializer(AssistantConversationSerializer):
    messages = AssistantMessageSerializer(many=True, read_only=True)

    class Meta(AssistantConversationSerializer.Meta):
        fields = AssistantConversationSerializer.Meta.fields + ["messages"]
