from django import forms

from dashboard.models import KYCProfile


class KYCSubmissionForm(forms.ModelForm):
    class Meta:
        model = KYCProfile
        fields = [
            "full_name",
            "date_of_birth",
            "nationality",
            "phone",
            "address",
            "id_document_type",
            "id_document_number",
            "id_document_front",
            "id_document_back",
            "selfie_photo",
            "proof_of_address",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "address": forms.Textarea(attrs={"rows": 4}),
        }

    def clean(self):
        cleaned_data = super().clean()

        required_fields = [
            "full_name",
            "date_of_birth",
            "nationality",
            "phone",
            "address",
            "id_document_type",
            "id_document_number",
            "id_document_front",
            "selfie_photo",
            "proof_of_address",
        ]

        for field in required_fields:
            if not cleaned_data.get(field):
                self.add_error(field, "Ce champ est obligatoire.")

        return cleaned_data