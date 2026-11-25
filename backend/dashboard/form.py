from pathlib import Path

from django import forms
from django.conf import settings

from dashboard.models import KYCProfile


class KYCSubmissionForm(forms.ModelForm):
    FILE_FIELDS = (
        "id_document_front",
        "id_document_back",
        "selfie_photo",
        "proof_of_address",
    )
    ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}
    ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "application/pdf"}

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

        for field_name in self.FILE_FIELDS:
            uploaded_file = cleaned_data.get(field_name)
            if uploaded_file and hasattr(uploaded_file, "content_type"):
                self._validate_uploaded_file(field_name, uploaded_file)

        return cleaned_data

    def _validate_uploaded_file(self, field_name, uploaded_file):
        max_size = settings.KYC_MAX_FILE_SIZE_BYTES
        if uploaded_file.size > max_size:
            max_megabytes = max_size // (1024 * 1024)
            self.add_error(field_name, f"Le fichier dépasse {max_megabytes} Mo.")
            return

        extension = Path(uploaded_file.name).suffix.lower()
        if extension not in self.ALLOWED_EXTENSIONS:
            self.add_error(field_name, "Formats autorisés : JPG, PNG ou PDF.")
            return

        if uploaded_file.content_type not in self.ALLOWED_CONTENT_TYPES:
            self.add_error(field_name, "Le type de fichier est invalide.")
            return

        header = uploaded_file.read(8)
        uploaded_file.seek(0)
        signatures = {
            ".jpg": header.startswith(b"\xff\xd8\xff"),
            ".jpeg": header.startswith(b"\xff\xd8\xff"),
            ".png": header.startswith(b"\x89PNG\r\n\x1a\n"),
            ".pdf": header.startswith(b"%PDF-"),
        }
        if not signatures.get(extension, False):
            self.add_error(field_name, "Le contenu du fichier ne correspond pas à son format.")
