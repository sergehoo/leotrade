from rest_framework import serializers

from leo_backtesting.models import BacktestRun


class BacktestRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = BacktestRun
        fields = "__all__"