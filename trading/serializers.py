from rest_framework import serializers
from .models import Order, TradeExecution


class HistoricalReadOnlySerializer(serializers.ModelSerializer):
    def create(self, validated_data):
        raise serializers.ValidationError(
            "Cette ressource historique est en lecture seule."
        )

    def update(self, instance, validated_data):
        raise serializers.ValidationError(
            "Cette ressource historique est en lecture seule."
        )


class OrderSerializer(HistoricalReadOnlySerializer):
    class Meta:
        model = Order
        fields = "__all__"
        read_only_fields = [field.name for field in Order._meta.fields]


class TradeExecutionSerializer(HistoricalReadOnlySerializer):
    class Meta:
        model = TradeExecution
        fields = "__all__"
        read_only_fields = [field.name for field in TradeExecution._meta.fields]
