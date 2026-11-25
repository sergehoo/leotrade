from django.conf import settings
from django.db import models


class KYCProfile(models.Model):
    STATUS_CHOICES = [
        ("NOT_STARTED", "Not started"),
        ("PENDING", "Pending"),
        ("UNDER_REVIEW", "Under review"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    ]

    DOCUMENT_TYPE_CHOICES = [
        ("NATIONAL_ID", "National ID"),
        ("PASSPORT", "Passport"),
        ("DRIVING_LICENSE", "Driving License"),
        ("RESIDENCE_PERMIT", "Residence Permit"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="kyc_profile"
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="NOT_STARTED")

    full_name = models.CharField(max_length=255, blank=True)
    date_of_birth = models.DateField(blank=True, null=True)
    nationality = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)

    id_document_type = models.CharField(max_length=50, choices=DOCUMENT_TYPE_CHOICES, blank=True)
    id_document_number = models.CharField(max_length=100, blank=True)

    id_document_front = models.FileField(upload_to="kyc/id/front/", blank=True, null=True)
    id_document_back = models.FileField(upload_to="kyc/id/back/", blank=True, null=True)
    selfie_photo = models.FileField(upload_to="kyc/selfie/", blank=True, null=True)
    proof_of_address = models.FileField(upload_to="kyc/address/", blank=True, null=True)

    rejection_reason = models.TextField(blank=True)
    admin_note = models.TextField(blank=True)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="kyc_reviewed_profiles",
    )
    reviewed_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"KYC {self.user} - {self.status}"