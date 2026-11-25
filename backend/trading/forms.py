"""
trading/forms.py
================

Formulaires Trading avec validations croisées strictes.
"""

from decimal import Decimal

from django import forms

from .models import TradingIntent


class TradingIntentForm(forms.ModelForm):
    """
    Création / édition d'une intention de trading.
    Validations métier :
    - capital_amount strictement positif et plafonné par tier KYC
    - target_return_percent dans [0; 1000]
    - max_loss_percent dans [0; 100], avec ratio sain risque/récompense
    - duration_days dans [1; 365]
    - max_open_positions dans [1; 50]
    """

    # Plafonds globaux (à externaliser en config selon le tier KYC à terme)
    CAPITAL_MAX = Decimal("1000000.00")           # 1 M€ par intention
    TARGET_RETURN_MAX = 1000.0                    # 1000 %
    MAX_LOSS_PERCENT_MAX = 100.0                  # 100 %
    DURATION_MIN = 1
    DURATION_MAX = 365
    MAX_OPEN_POSITIONS_MAX = 50

    class Meta:
        model = TradingIntent
        fields = [
            "broker_account",
            "portfolio",
            "title",
            "capital_amount",
            "capital_currency",
            "target_return_percent",
            "max_loss_percent",
            "duration_days",
            "max_open_positions",
            "risk_level",
            "execution_mode",
            "allowed_asset_classes",
            "objective_prompt",
        ]
        widgets = {
            "objective_prompt": forms.Textarea(attrs={"rows": 4}),
        }

    # ----- bornes par champ -----

    def clean_capital_amount(self):
        v = self.cleaned_data.get("capital_amount")
        if v is None:
            return v
        v = Decimal(str(v))
        if v <= 0:
            raise forms.ValidationError("Le capital doit être strictement positif.")
        if v > self.CAPITAL_MAX:
            raise forms.ValidationError(
                f"Le capital par intention est plafonné à {self.CAPITAL_MAX}."
            )
        return v

    def clean_target_return_percent(self):
        v = self.cleaned_data.get("target_return_percent")
        if v is None:
            return v
        if v < 0:
            raise forms.ValidationError("L'objectif de rendement ne peut pas être négatif.")
        if v > self.TARGET_RETURN_MAX:
            raise forms.ValidationError(
                f"L'objectif de rendement ne peut pas dépasser {self.TARGET_RETURN_MAX} %."
            )
        return v

    def clean_max_loss_percent(self):
        v = self.cleaned_data.get("max_loss_percent")
        if v is None:
            return v
        if v < 0:
            raise forms.ValidationError("La perte maximale ne peut pas être négative.")
        if v > self.MAX_LOSS_PERCENT_MAX:
            raise forms.ValidationError(
                f"La perte maximale ne peut pas dépasser {self.MAX_LOSS_PERCENT_MAX} %."
            )
        return v

    def clean_duration_days(self):
        v = self.cleaned_data.get("duration_days")
        if v is None:
            return v
        if v < self.DURATION_MIN or v > self.DURATION_MAX:
            raise forms.ValidationError(
                f"Durée invalide. Plage autorisée : {self.DURATION_MIN}–{self.DURATION_MAX} jours."
            )
        return v

    def clean_max_open_positions(self):
        v = self.cleaned_data.get("max_open_positions")
        if v is None:
            return v
        if v < 1 or v > self.MAX_OPEN_POSITIONS_MAX:
            raise forms.ValidationError(
                f"Nombre de positions invalide (1–{self.MAX_OPEN_POSITIONS_MAX})."
            )
        return v

    # ----- validations croisées -----

    def clean(self):
        cleaned = super().clean()

        target = cleaned.get("target_return_percent")
        max_loss = cleaned.get("max_loss_percent")

        # Cohérence : on accepte des objectifs ambitieux MAIS la perte max
        # doit rester strictement inférieure à 50 % pour rester gérable.
        if max_loss is not None and max_loss > 50:
            self.add_error(
                "max_loss_percent",
                "Une perte maximale supérieure à 50 % rend l'intention ingérable. "
                "Réduisez le risque ou augmentez le capital.",
            )

        # Si target et max_loss sont définis, on demande un ratio R:R ≥ 1
        # (l'objectif doit être au moins égal à la perte max acceptée).
        if target is not None and max_loss is not None and max_loss > 0:
            if target < max_loss:
                self.add_error(
                    "target_return_percent",
                    "L'objectif de rendement doit être au moins égal à la perte maximale "
                    "acceptée (ratio risque/récompense ≥ 1).",
                )

        return cleaned
