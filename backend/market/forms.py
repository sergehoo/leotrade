from django import forms
from .models import Asset, Timeframe


class AssetForm(forms.ModelForm):
    class Meta:
        model = Asset
        fields = "__all__"


class TimeframeForm(forms.ModelForm):
    class Meta:
        model = Timeframe
        fields = "__all__"