from django import forms
from .models import BacktestRun


class BacktestRunForm(forms.ModelForm):
    class Meta:
        model = BacktestRun
        fields = [
            "strategy",
            "name",
            "start_date",
            "end_date",
            "initial_cash",
            "commission",
            "spread",
            "slippage",
            "parameters",
        ]
