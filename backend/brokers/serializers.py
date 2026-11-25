from rest_framework import serializers
from .models import BrokerAccount


class BrokerAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = BrokerAccount
        fields = "__all__"