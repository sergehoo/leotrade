from django import forms
from brokers.models import BrokerAccount
from django import forms
from .models import BrokerAccount

class BrokerAccountForm(forms.ModelForm):
    api_key = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=True),
        label="API Key",
    )
    api_secret = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=True),
        label="API Secret",
    )
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=True),
        label="Password",
    )
    deriv_token = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=True),
        label="Deriv Token",
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Préremplissage des secrets existants en édition
        if self.instance and self.instance.pk:
            self.fields["api_key"].initial = self.instance.api_key
            self.fields["api_secret"].initial = self.instance.api_secret
            self.fields["password"].initial = self.instance.password
            self.fields["deriv_token"].initial = self.instance.deriv_token

    def clean(self):
        cleaned = super().clean()
        broker = cleaned.get("broker")

        # On laisse le modèle faire les validations métier principales,
        # mais on peut ajouter ici des règles UI complémentaires si besoin.
        if broker == "BINANCE":
            pass
        elif broker == "MT5":
            pass
        elif broker == "DERIV":
            pass

        return cleaned

    def save(self, commit=True, user=None):
        instance = super().save(commit=False)

        if user is not None:
            instance.user = user

        # status n'est pas exposé au formulaire ; on le pilote côté système
        if not instance.status:
            instance.status = "DRAFT"

        if commit:
            instance.save()

        api_key = self.cleaned_data.get("api_key")
        api_secret = self.cleaned_data.get("api_secret")
        password = self.cleaned_data.get("password")
        deriv_token = self.cleaned_data.get("deriv_token")

        if api_key:
            instance.set_secret("API_KEY", api_key, created_by=user)
        if api_secret:
            instance.set_secret("API_SECRET", api_secret, created_by=user)
        if password:
            instance.set_secret("PASSWORD", password, created_by=user)
        if deriv_token:
            instance.set_secret("DERIV_TOKEN", deriv_token, created_by=user)

        return instance

# class BrokerAccountForm(forms.ModelForm):
#     class Meta:
#         model = BrokerAccount
#         fields = [
#             "name",
#             "broker",
#             "mode",
#             "api_key",
#             "api_secret",
#             "login",
#             "password",
#             "server",
#             "terminal_path",
#             "deriv_token",
#             "deriv_app_id",
#             "deriv_currency",
#             "deriv_account_type",
#             "is_active",
#             "is_default",
#         ]
#         widgets = {
#             "password": forms.PasswordInput(render_value=True),
#             "api_secret": forms.PasswordInput(render_value=True),
#             "deriv_token": forms.PasswordInput(render_value=True),
#         }
#
#     def clean(self):
#         cleaned = super().clean()
#         broker = cleaned.get("broker")
#
#         if broker == "BINANCE":
#             if not cleaned.get("api_key"):
#                 self.add_error("api_key", "L'API key Binance est requise.")
#             if not cleaned.get("api_secret"):
#                 self.add_error("api_secret", "L'API secret Binance est requis.")
#
#         elif broker == "MT5":
#             required_fields = {
#                 "login": "Le login MT5 est requis.",
#                 "password": "Le mot de passe MT5 est requis.",
#                 "server": "Le serveur MT5 est requis.",
#             }
#             for field, message in required_fields.items():
#                 if not cleaned.get(field):
#                     self.add_error(field, message)
#
#         elif broker == "DERIV":
#             if not cleaned.get("deriv_token"):
#                 self.add_error("deriv_token", "Le token Deriv est requis.")
#             if not cleaned.get("deriv_app_id"):
#                 self.add_error("deriv_app_id", "Le app_id Deriv est requis.")
#
#         return cleaned