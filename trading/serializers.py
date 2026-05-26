from rest_framework import serializers
from .models import Order, TradeExecution


class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = "__all__"


class TradeExecutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TradeExecution
        fields = "__all__"