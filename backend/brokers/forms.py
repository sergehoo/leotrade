from django import forms

from .models import BrokerAccount


class BrokerAccountForm(forms.ModelForm):
    SECRET_HELP = (
        "Laissez vide pour conserver la valeur chiffrée existante. "
        "Une valeur enregistrée n'est jamais réaffichée."
    )

    api_key = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        label="API Key",
        help_text=SECRET_HELP,
    )
    api_secret = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        label="API Secret",
        help_text=SECRET_HELP,
    )
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        label="Password",
        help_text=SECRET_HELP,
    )
    deriv_token = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        label="Deriv Token",
        help_text=SECRET_HELP,
    )

    class Meta:
        model = BrokerAccount
        fields = [
            "name",
            "broker",
            "mode",
            "login",
            "server",
            "terminal_path",
            "deriv_app_id",
            "deriv_currency",
            "deriv_account_type",
            "is_active",
            "is_default",
            "notes",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "broker": forms.Select(attrs={"class": "form-select"}),
            "mode": forms.Select(attrs={"class": "form-select"}),
            "login": forms.TextInput(attrs={"class": "form-control"}),
            "server": forms.TextInput(attrs={"class": "form-control"}),
            "terminal_path": forms.TextInput(attrs={"class": "form-control"}),
            "deriv_app_id": forms.TextInput(attrs={"class": "form-control"}),
            "deriv_currency": forms.TextInput(attrs={"class": "form-control"}),
            "deriv_account_type": forms.TextInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_default": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def save(self, commit=True, user=None):
        instance = super().save(commit=False)

        if user is not None:
            instance.user = user
        if not instance.status:
            instance.status = "DRAFT"
        if commit:
            instance.save()

        for field_name, secret_type in (
            ("api_key", "API_KEY"),
            ("api_secret", "API_SECRET"),
            ("password", "PASSWORD"),
            ("deriv_token", "DERIV_TOKEN"),
        ):
            value = self.cleaned_data.get(field_name)
            if value:
                instance.set_secret(secret_type, value, created_by=user)

        return instance
