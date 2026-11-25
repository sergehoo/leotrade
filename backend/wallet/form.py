"""
wallet/form.py
==============

Formulaires Wallet, validés strictement (montants min/max, cohérence métier).
"""

from decimal import Decimal

from django import forms
from django.conf import settings

from .models import PayoutDestination, WithdrawalRequest
from .services import PaymentGatewayValidationError, PaystackWalletService


# Plafonds globaux par opération. À ajuster en config selon le KYC tier.
DEPOSIT_MIN = Decimal("1.00")
DEPOSIT_MAX = Decimal("100000.00")          # 100 000 / opération
WITHDRAWAL_MIN = Decimal("5.00")
WITHDRAWAL_MAX = Decimal("100000.00")


class DepositForm(forms.Form):
    PROVIDER_CHOICES = [
        ("PAYSTACK", "Paystack"),
        ("STRIPE", "Stripe"),
        ("ADYEN", "Adyen"),
    ]
    CURRENCY_CHOICES = [
        ("XOF", "XOF — Franc CFA"),
        ("NGN", "NGN — Naira"),
        ("GHS", "GHS — Cedi"),
        ("KES", "KES — Shilling kényan"),
        ("ZAR", "ZAR — Rand"),
        ("USD", "USD"),
        ("EUR", "EUR"),
    ]

    amount = forms.DecimalField(
        min_value=DEPOSIT_MIN,
        max_value=DEPOSIT_MAX,
        decimal_places=2,
        max_digits=18,
        label="Montant",
        help_text=f"Entre {DEPOSIT_MIN} et {DEPOSIT_MAX}.",
    )
    currency = forms.ChoiceField(choices=CURRENCY_CHOICES, initial="USD", label="Devise")
    provider = forms.ChoiceField(choices=PROVIDER_CHOICES, initial="PAYSTACK", label="Fournisseur")

    def __init__(self, *args, wallet=None, **kwargs):
        self.wallet = wallet
        super().__init__(*args, **kwargs)
        configured_default = getattr(settings, "PAYMENT_DEFAULT_PROVIDER", "PAYSTACK").upper()
        valid_providers = {code for code, _ in self.PROVIDER_CHOICES}
        self.fields["provider"].initial = (
            configured_default if configured_default in valid_providers else "PAYSTACK"
        )

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        # Re-validation côté serveur, ne pas se fier au front
        if amount < DEPOSIT_MIN:
            raise forms.ValidationError(f"Le montant minimum est {DEPOSIT_MIN}.")
        if amount > DEPOSIT_MAX:
            raise forms.ValidationError(f"Le montant maximum par opération est {DEPOSIT_MAX}.")
        return amount

    def clean(self):
        cleaned_data = super().clean()
        amount = cleaned_data.get("amount")
        currency = cleaned_data.get("currency")
        provider = cleaned_data.get("provider")

        if self.wallet and currency and currency.upper() != self.wallet.currency.upper():
            self.add_error(
                "currency",
                f"Ce wallet accepte uniquement les dépôts en {self.wallet.currency.upper()}.",
            )

        if provider == "PAYSTACK" and amount is not None and currency:
            try:
                PaystackWalletService.amount_to_subunit(amount, currency)
            except PaymentGatewayValidationError as exc:
                self.add_error("amount", str(exc))
        return cleaned_data


class WithdrawalForm(forms.ModelForm):
    class Meta:
        model = WithdrawalRequest
        fields = ["amount", "currency", "destination_type", "destination_masked"]
        widgets = {
            "destination_masked": forms.TextInput(
                attrs={"placeholder": "Ex: Banque ****1234 ou Carte ****4242"}
            ),
        }

    def __init__(self, *args, wallet=None, **kwargs):
        self.wallet = wallet
        super().__init__(*args, **kwargs)

        # Bornes sur le champ amount du modèle
        self.fields["amount"].min_value = WITHDRAWAL_MIN
        self.fields["amount"].max_value = WITHDRAWAL_MAX
        self.fields["amount"].help_text = (
            f"Entre {WITHDRAWAL_MIN} et {WITHDRAWAL_MAX}."
        )

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount < WITHDRAWAL_MIN:
            raise forms.ValidationError(f"Le montant minimum est {WITHDRAWAL_MIN}.")
        if amount > WITHDRAWAL_MAX:
            raise forms.ValidationError(f"Le montant maximum par opération est {WITHDRAWAL_MAX}.")
        if self.wallet and amount > (self.wallet.available_balance or Decimal("0")):
            raise forms.ValidationError(
                "Le solde disponible ne couvre pas ce retrait."
            )
        return amount


class PayoutDestinationForm(forms.ModelForm):
    class Meta:
        model = PayoutDestination
        fields = [
            "destination_type",
            "label",
            "account_name",
            "bank_name",
            "iban",
            "phone_number",
            "mobile_money_operator",
            "country_code",
            "currency",
            "provider_reference",
            "is_default",
            # NOTE : is_verified est intentionnellement exclu du formulaire utilisateur.
            # La vérification est effectuée exclusivement par un administrateur (staff).
        ]
