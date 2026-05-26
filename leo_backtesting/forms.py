from django import forms
from .models import BacktestRun


class BacktestRunForm(forms.ModelForm):
    class Meta:
        model = BacktestRun
        fields = "__all__"