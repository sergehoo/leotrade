from django import forms
from .models import Portfolio, Position, PortfolioAllocation


class PortfolioForm(forms.ModelForm):
    class Meta:
        model = Portfolio
        fields = [
            "broker_account",
            "name",
            "description",
            "base_currency",
            "starting_balance",
            "is_active",
            "is_default",
            "notes",
        ]


class PositionForm(forms.ModelForm):
    class Meta:
        model = Position
        fields = [
            "asset",
            "symbol",
            "asset_name",
            "side",
            "quantity",
            "entry_price",
            "average_entry_price",
            "current_price",
            "stop_loss",
            "take_profit",
            "leverage",
            "margin_used",
            "status",
            "source",
            "cost_basis_status",
            "opened_at",
            "closed_at",
        ]
        widgets = {
            "opened_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "closed_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }


class PortfolioAllocationForm(forms.ModelForm):
    class Meta:
        model = PortfolioAllocation
        fields = [
            "asset",
            "target_weight",
            "max_weight",
            "is_active",
        ]