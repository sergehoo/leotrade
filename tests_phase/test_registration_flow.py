from pathlib import Path
from urllib.parse import urlsplit

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.core import mail
from django.test import override_settings
from django.template.loader import get_template
from django.urls import reverse


PROJECT_ROOT = Path(__file__).resolve().parents[1]


ACCOUNT_PAGE_TEMPLATES = [
    "account/account_inactive.html",
    "account/email.html",
    "account/email_confirm.html",
    "account/login.html",
    "account/logout.html",
    "account/password_change.html",
    "account/password_reset.html",
    "account/password_reset_done.html",
    "account/password_reset_from_key.html",
    "account/password_reset_from_key_done.html",
    "account/password_set.html",
    "account/reauthenticate.html",
    "account/signup.html",
    "account/signup_closed.html",
    "account/verification_sent.html",
    "account/verified_email_required.html",
]


def test_account_pages_use_the_lyneci_layout():
    for template_name in ACCOUNT_PAGE_TEMPLATES:
        get_template(template_name)
        source = (PROJECT_ROOT / "templates" / template_name).read_text()

        assert '{% extends "account/base.html" %}' in source
        assert "Best-Épargne" not in source
        assert "LeoTrade" not in source
        assert "account/_base.html" not in source


def test_transactional_account_emails_are_branded_and_multipart():
    email_dir = PROJECT_ROOT / "templates" / "account" / "email"
    expected_prefixes = [
        "email_confirmation",
        "email_confirmation_signup",
        "password_reset_key",
        "account_already_exists",
        "unknown_account",
        "password_changed",
        "password_reset",
        "password_set",
        "email_changed",
        "email_deleted",
        "email_confirm",
    ]

    for prefix in expected_prefixes:
        assert (email_dir / f"{prefix}_subject.txt").is_file()
        assert (email_dir / f"{prefix}_message.txt").is_file()
        assert (email_dir / f"{prefix}_message.html").is_file()

    combined = "\n".join(path.read_text() for path in email_dir.iterdir())
    assert "Lyneci" in combined
    assert "Best-Épargne" not in combined
    assert "LeoTrade" not in combined


@pytest.mark.django_db
@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    ACCOUNT_DEFAULT_HTTP_PROTOCOL="https",
    ALLOWED_HOSTS=["lyneci.test", "testserver"],
)
def test_signup_sends_confirmation_and_confirmation_activates_login(client, settings):
    Site.objects.update_or_create(
        pk=settings.SITE_ID,
        defaults={"domain": "lyneci.test", "name": "Lyneci — Intelligent Trading"},
    )

    response = client.post(
        reverse("account_signup"),
        {
            "email": "new.trader@lyneci.test",
            "password1": "SafeRegistration42!",
            "password2": "SafeRegistration42!",
            "website": "",
        },
        secure=True,
        HTTP_HOST="lyneci.test",
    )

    assert response.status_code == 302
    assert response.url == reverse("account_email_verification_sent")

    user = get_user_model().objects.get(email="new.trader@lyneci.test")
    email_address = EmailAddress.objects.get(user=user, email=user.email)
    assert email_address.verified is False
    assert "_auth_user_id" not in client.session

    assert len(mail.outbox) == 1
    confirmation_email = mail.outbox[0]
    assert confirmation_email.subject.startswith("[Lyneci]")
    assert "https://lyneci.test/accounts/confirm-email/" in confirmation_email.body
    assert confirmation_email.alternatives
    assert "Lyneci" in confirmation_email.alternatives[0].content

    confirmation_url = next(
        line.strip()
        for line in confirmation_email.body.splitlines()
        if "/accounts/confirm-email/" in line
    )
    confirmation_path = urlsplit(confirmation_url).path

    confirmation_page = client.get(
        confirmation_path,
        secure=True,
        HTTP_HOST="lyneci.test",
    )
    assert confirmation_page.status_code == 200
    assert user.email in confirmation_page.content.decode()

    confirmation_response = client.post(
        confirmation_path,
        secure=True,
        HTTP_HOST="lyneci.test",
    )
    assert confirmation_response.status_code == 302

    email_address.refresh_from_db()
    assert email_address.verified is True
    assert client.session.get("_auth_user_id") == str(user.pk)


@pytest.mark.django_db
@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    ACCOUNT_DEFAULT_HTTP_PROTOCOL="https",
    ALLOWED_HOSTS=["lyneci.test", "testserver"],
)
def test_password_reset_email_is_branded_and_does_not_enumerate(client, settings):
    Site.objects.update_or_create(
        pk=settings.SITE_ID,
        defaults={"domain": "lyneci.test", "name": "Lyneci — Intelligent Trading"},
    )
    user = get_user_model().objects.create_user(
        username="recovery-user",
        email="recovery@lyneci.test",
        password="ExistingPassword42!",
    )
    EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)

    known_response = client.post(
        reverse("account_reset_password"),
        {"email": user.email},
        secure=True,
        HTTP_HOST="lyneci.test",
    )
    unknown_response = client.post(
        reverse("account_reset_password"),
        {"email": "unknown@lyneci.test"},
        secure=True,
        HTTP_HOST="lyneci.test",
    )

    assert known_response.status_code == 302
    assert unknown_response.status_code == 302
    assert known_response.url == unknown_response.url == reverse("account_reset_password_done")
    assert len(mail.outbox) == 2
    assert all(message.subject.startswith("[Lyneci]") for message in mail.outbox)
    assert all(message.alternatives for message in mail.outbox)
    assert "password/reset/key/" in mail.outbox[0].body
    assert "aucun compte Lyneci" in mail.outbox[1].body
