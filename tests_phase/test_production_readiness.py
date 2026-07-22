from datetime import date
from pathlib import Path

import pytest
import yaml
from django.contrib.sites.models import Site
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import get_template
from django.test import override_settings
from django.urls import reverse

from dashboard.form import KYCSubmissionForm
from dashboard.models import KYCProfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _kyc_payload():
    return {
        "full_name": "Test Client",
        "date_of_birth": date(1990, 1, 1),
        "nationality": "CI",
        "phone": "+2250102030405",
        "address": "Abidjan",
        "id_document_type": "PASSPORT",
        "id_document_number": "CI123456",
    }


def _valid_files():
    return {
        "id_document_front": SimpleUploadedFile(
            "passport.pdf",
            b"%PDF-1.4\nvalid",
            content_type="application/pdf",
        ),
        "selfie_photo": SimpleUploadedFile(
            "selfie.jpg",
            b"\xff\xd8\xff\xe0valid",
            content_type="image/jpeg",
        ),
        "proof_of_address": SimpleUploadedFile(
            "address.png",
            b"\x89PNG\r\n\x1a\nvalid",
            content_type="image/png",
        ),
    }


def test_kyc_form_accepts_valid_signed_documents():
    form = KYCSubmissionForm(data=_kyc_payload(), files=_valid_files())
    assert form.is_valid(), form.errors


def test_kyc_form_rejects_spoofed_document_content():
    files = _valid_files()
    files["id_document_front"] = SimpleUploadedFile(
        "passport.pdf",
        b"not-a-pdf",
        content_type="application/pdf",
    )
    form = KYCSubmissionForm(data=_kyc_payload(), files=files)
    assert not form.is_valid()
    assert "contenu du fichier" in form.errors["id_document_front"][0]


@pytest.mark.django_db
def test_kyc_documents_are_staff_only(client, user, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    profile = KYCProfile.objects.create(
        user=user,
        id_document_front=SimpleUploadedFile(
            "passport.pdf",
            b"%PDF-1.4\nprivate",
            content_type="application/pdf",
        ),
    )
    url = reverse("admin-kyc-document", args=[profile.pk, "id_document_front"])

    client.force_login(user)
    assert client.get(url).status_code == 302

    user.is_staff = True
    user.save(update_fields=["is_staff"])
    response = client.get(url)
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert response["X-Content-Type-Options"] == "nosniff"


@override_settings(METRICS_AUTH_TOKEN="production-metrics-token")
def test_metrics_require_the_configured_bearer_token(client):
    assert client.get("/metrics").status_code == 403
    assert client.get(
        "/metrics",
        HTTP_AUTHORIZATION="Bearer production-metrics-token",
    ).status_code == 200


def test_runtime_templates_are_loadable():
    template_names = [
        "dashboard/admin/kyc_list.html",
        "dashboard/admin/kyc_detail.html",
        "wallet/admin/withdrawal_queue.html",
        "wallet/admin/withdrawal_detail.html",
        "wallet/admin/wallet_list.html",
        "wallet/admin/wallet_detail.html",
        "execution/order_list.html",
        "execution/order_detail.html",
        "400.html",
        "403.html",
        "404.html",
        "500.html",
    ]
    for template_name in template_names:
        assert get_template(template_name)


def test_public_home_uses_lyneci_identity(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "Lyneci — Intelligent Trading" in response.content.decode()
    assert "LeoTrade" not in response.content.decode()


def test_compose_uses_shared_external_traefik():
    compose = yaml.safe_load((PROJECT_ROOT / "docker_compose.yml").read_text())
    services = compose["services"]

    assert "traefik" not in services
    assert set(services) == {
        "lyneci-db",
        "lyneci-redis",
        "lyneci-release",
        "lyneci-web",
        "lyneci-worker",
        "lyneci-beat",
        "lyneci-flower",
    }
    assert compose["networks"]["proxy"]["external"] is True

    web_labels = services["lyneci-web"]["labels"]
    assert "traefik.docker.network=${TRAEFIK_NETWORK:-proxy}" in web_labels
    assert any("tls.certresolver=${TRAEFIK_CERT_RESOLVER:-lets}" in label for label in web_labels)


@pytest.mark.django_db
@override_settings(
    SITE_ID=1,
    SITE_BASE_URL="https://lyneci.com",
    BRAND_FULL_NAME="Lyneci — Intelligent Trading",
)
def test_site_identity_command_configures_public_brand():
    call_command("configure_site_identity")

    site = Site.objects.get(pk=1)
    assert site.domain == "lyneci.com"
    assert site.name == "Lyneci — Intelligent Trading"
