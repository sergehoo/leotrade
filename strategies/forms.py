from django import forms
from .models import Strategy


class StrategyForm(forms.ModelForm):
    class Meta:
        model = Strategy
        fields = "__all__"
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "entry_rules": forms.Textarea(attrs={"rows": 5}),
            "exit_rules": forms.Textarea(attrs={"rows": 5}),
            "parameters": forms.Textarea(attrs={"rows": 5}),
        }