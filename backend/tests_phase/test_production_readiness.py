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
from core.checks import production_configuration_checks


PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Monorepo : le backend Django vit dans backend/, les artefacts d'infra
# (Docker, Compose, gabarits d'environnement) vivent dans infrastructure/.
REPO_ROOT = PROJECT_ROOT.parent
INFRA_ROOT = REPO_ROOT / "infrastructure"


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
        "account/verification_sent.html",
        "account/email_confirm.html",
        "400.html",
        "403.html",
        "404.html",
        "500.html",
    ]
    for template_name in template_names:
        assert get_template(template_name)


def test_public_home_uses_leotrade_identity(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "LeoTrade — Intelligent Trading" in response.content.decode()
    assert "Lyneci" not in response.content.decode()


@pytest.mark.django_db
def test_email_verification_sent_page_has_visible_leotrade_content(client):
    response = client.get(reverse("account_email_verification_sent"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Confirmez votre adresse email" in content
    assert "Vérifiez votre email — LeoTrade" in content
    assert "Best-Épargne" not in content


def test_compose_uses_shared_external_traefik():
    compose = yaml.safe_load((INFRA_ROOT / "docker" / "docker-compose.yml").read_text())
    services = compose["services"]

    assert "traefik" not in services
    assert set(services) == {
        "leotrade-db",
        "leotrade-redis",
        "leotrade-release",
        "leotrade-web",
        "leotrade-worker",
        "leotrade-beat",
        "leotrade-flower",
    }
    assert compose["networks"]["proxy"]["external"] is True

    web_labels = services["leotrade-web"]["labels"]
    assert "traefik.docker.network=${TRAEFIK_NETWORK:-proxy}" in web_labels
    assert any("tls.certresolver=${TRAEFIK_CERT_RESOLVER:-lets}" in label for label in web_labels)
    assert any(
        "leotrade-web-sec-headers.headers.referrerPolicy=strict-origin-when-cross-origin"
        in label
        for label in web_labels
    )
    router_middlewares = next(
        label
        for label in web_labels
        if label.startswith("traefik.http.routers.leotrade-web.middlewares=")
    )
    assert ",sec-headers@docker" not in router_middlewares
    assert "Host: $$TRAEFIK_APP_HOST" in services["leotrade-web"]["healthcheck"]["test"][1]
    assert "X-Forwarded-Proto: https" in services["leotrade-web"]["healthcheck"]["test"][1]


def test_optional_sentry_dsn_is_empty_by_default():
    portable_example = INFRA_ROOT / "deploy" / "production.env.example"
    dotfile_example = INFRA_ROOT / "deploy" / ".env.prod.example"
    if dotfile_example.exists():
        assert dotfile_example.read_text() == portable_example.read_text()
    environment = portable_example.read_text().splitlines()
    assert "SENTRY_DSN=" in environment
    assert not any(line.startswith("SENTRY_DSN=REPLACE_") for line in environment)
    assert "TRAEFIK_SHARED_MIDDLEWARES=compress@docker,ratelimit@docker" in environment


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
    EMAIL_HOST="REPLACE_WITH_SMTP_HOST",
    EMAIL_HOST_USER="REPLACE_WITH_SMTP_USER",
    EMAIL_HOST_PASSWORD="REPLACE_WITH_SMTP_PASSWORD",
)
def test_production_check_rejects_placeholder_smtp_configuration():
    error_ids = {
        error.id
        for error in production_configuration_checks(None)
    }

    assert "leotrade.E015" in error_ids


def test_docker_image_builds_a_writable_production_static_manifest():
    dockerfile = (INFRA_ROOT / "docker" / "Dockerfile").read_text()
    collectstatic = dockerfile.index(
        "DJANGO_SETTINGS_MODULE=leoTrade.settings.base \\\n"
        "       python manage.py collectstatic --noinput --skip-checks"
    )
    final_chown = dockerfile.index(
        "chown -R leotrade:leotrade /app/staticfiles",
        collectstatic,
    )

    assert final_chown > collectstatic


@pytest.mark.django_db
@override_settings(
    SITE_ID=1,
    SITE_BASE_URL="https://leotrade.com",
    BRAND_FULL_NAME="LeoTrade — Intelligent Trading",
)
def test_site_identity_command_configures_public_brand():
    call_command("configure_site_identity")

    site = Site.objects.get(pk=1)
    assert site.domain == "leotrade.com"
    assert site.name == "LeoTrade — Intelligent Trading"
