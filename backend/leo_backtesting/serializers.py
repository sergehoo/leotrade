from rest_framework import serializers

from leo_backtesting.models import BacktestRun


class BacktestRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = BacktestRun
        fields = [
            "id",
            "strategy",
            "name",
            "start_date",
            "end_date",
            "initial_cash",
            "commission",
            "spread",
            "slippage",
            "parameters",
            "metrics",
            "equity_curve",
            "trades_log",
            "status",
            "engine_version",
            "data_points",
            "data_checksum",
            "started_at",
            "completed_at",
            "failure_message",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
