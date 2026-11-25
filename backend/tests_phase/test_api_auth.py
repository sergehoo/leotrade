"""Socle d'authentification de l'API v1 (clients React / Flutter).

Ces tests verrouillent les garanties de sécurité du parcours de connexion.
La plus importante : la présence d'un second facteur ne doit jamais pouvoir
être contournée en passant par l'API plutôt que par le web.
"""

from __future__ import annotations

import pytest
from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()

PASSWORD = "Correct-Horse-Battery-42"


def _verified_user(email="trader@example.test", username="trader"):
    user = User.objects.create_user(
        username=username, email=email, password=PASSWORD
    )
    EmailAddress.objects.create(
        user=user, email=email, verified=True, primary=True
    )
    return user


@pytest.fixture
def user(db):
    return _verified_user()


@pytest.fixture(autouse=True)
def _reset_throttle_bucket():
    """Vide le compteur de throttling entre deux tests.

    Le throttle anonyme est indexé sur l'IP : dans la suite complète, tous
    les tests de ce module tapent depuis 127.0.0.1 et épuiseraient le même
    quota. On réinitialise plutôt que de désactiver, pour que le throttle
    reste réellement actif (cf. test_login_is_rate_limited).
    """
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_login_returns_token_pair_and_user(client, user):
    response = client.post(
        reverse("api-auth-login"),
        {"email": user.email, "password": PASSWORD},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["access"]
    assert body["refresh"]
    assert body["user"]["email"] == user.email
    # Aucun secret ne doit transiter dans l'identité.
    assert "password" not in body["user"]


@pytest.mark.django_db
def test_login_is_case_insensitive_on_email(client, user):
    response = client.post(
        reverse("api-auth-login"),
        {"email": user.email.upper(), "password": PASSWORD},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content


@pytest.mark.django_db
def test_login_with_wrong_password_does_not_reveal_account_existence(client, user):
    known = client.post(
        reverse("api-auth-login"),
        {"email": user.email, "password": "mauvais-mot-de-passe"},
        content_type="application/json",
    )
    unknown = client.post(
        reverse("api-auth-login"),
        {"email": "personne@example.test", "password": "mauvais-mot-de-passe"},
        content_type="application/json",
    )
    assert known.status_code == unknown.status_code == 400
    assert known.json() == unknown.json()


@pytest.mark.django_db
def test_login_refuses_unverified_email(client):
    User.objects.create_user(
        username="nonverifie", email="nonverifie@example.test", password=PASSWORD
    )
    response = client.post(
        reverse("api-auth-login"),
        {"email": "nonverifie@example.test", "password": PASSWORD},
        content_type="application/json",
    )
    assert response.status_code == 403
    assert response.json()["code"] == "EMAIL_NOT_VERIFIED"


@pytest.mark.django_db
def test_login_refuses_inactive_user(client, user):
    user.is_active = False
    user.save(update_fields=["is_active"])
    response = client.post(
        reverse("api-auth-login"),
        {"email": user.email, "password": PASSWORD},
        content_type="application/json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_login_with_totp_does_not_issue_tokens_without_the_code(client, user):
    """Garantie centrale : l'API ne contourne pas le second facteur."""
    from allauth.mfa import totp

    secret = totp.generate_totp_secret()
    Authenticator.objects.create(
        user=user,
        type=Authenticator.Type.TOTP,
        data={"secret": totp.encrypt(secret)},
    )

    response = client.post(
        reverse("api-auth-login"),
        {"email": user.email, "password": PASSWORD},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["mfa_required"] is True
    assert body["mfa_token"]
    # Aucun jeton d'accès ne doit être délivré à cette étape.
    assert "access" not in body
    assert "refresh" not in body


@pytest.mark.django_db
def test_mfa_step_issues_tokens_for_a_valid_totp_code(client, user):
    from allauth.mfa import totp

    secret = totp.generate_totp_secret()
    Authenticator.objects.create(
        user=user,
        type=Authenticator.Type.TOTP,
        data={"secret": totp.encrypt(secret)},
    )

    login = client.post(
        reverse("api-auth-login"),
        {"email": user.email, "password": PASSWORD},
        content_type="application/json",
    ).json()

    valid_code = totp.hotp_value(secret, totp.hotp_counter_from_time())
    response = client.post(
        reverse("api-auth-login-mfa"),
        {"mfa_token": login["mfa_token"], "code": totp.format_hotp_value(valid_code)},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    assert response.json()["access"]


@pytest.mark.django_db
def test_mfa_step_rejects_a_wrong_code(client, user):
    from allauth.mfa import totp

    secret = totp.generate_totp_secret()
    Authenticator.objects.create(
        user=user,
        type=Authenticator.Type.TOTP,
        data={"secret": totp.encrypt(secret)},
    )
    login = client.post(
        reverse("api-auth-login"),
        {"email": user.email, "password": PASSWORD},
        content_type="application/json",
    ).json()

    response = client.post(
        reverse("api-auth-login-mfa"),
        {"mfa_token": login["mfa_token"], "code": "000000"},
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.json()["code"] == "MFA_INVALID"


@pytest.mark.django_db
def test_mfa_token_cannot_be_forged(client, user):
    response = client.post(
        reverse("api-auth-login-mfa"),
        {"mfa_token": "jeton-fabrique-a-la-main", "code": "123456"},
        content_type="application/json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_me_requires_authentication(client):
    assert client.get(reverse("api-auth-me")).status_code == 401


@pytest.mark.django_db
def test_me_exposes_kyc_status_and_capabilities(client, user):
    tokens = client.post(
        reverse("api-auth-login"),
        {"email": user.email, "password": PASSWORD},
        content_type="application/json",
    ).json()

    response = client.get(
        reverse("api-auth-me"), HTTP_AUTHORIZATION=f"Bearer {tokens['access']}"
    )
    assert response.status_code == 200, response.content
    body = response.json()
    # Sans profil KYC, l'état est explicite — jamais inventé « approuvé ».
    assert body["kyc_status"] == "NOT_STARTED"
    assert body["capabilities"]["can_trade_live"] is False
    assert body["capabilities"]["can_trade_paper"] is True
    assert body["capabilities"]["can_withdraw"] is False


@pytest.mark.django_db
def test_capabilities_open_up_once_kyc_is_approved(client, user):
    from dashboard.models import KYCProfile

    KYCProfile.objects.create(user=user, status="APPROVED")
    tokens = client.post(
        reverse("api-auth-login"),
        {"email": user.email, "password": PASSWORD},
        content_type="application/json",
    ).json()
    body = client.get(
        reverse("api-auth-me"), HTTP_AUTHORIZATION=f"Bearer {tokens['access']}"
    ).json()
    assert body["kyc_status"] == "APPROVED"
    assert body["capabilities"]["can_trade_live"] is True
    assert body["capabilities"]["can_withdraw"] is True


@pytest.mark.django_db
def test_refresh_rotates_and_revokes_the_previous_token(client, user):
    tokens = client.post(
        reverse("api-auth-login"),
        {"email": user.email, "password": PASSWORD},
        content_type="application/json",
    ).json()

    refreshed = client.post(
        reverse("api-auth-refresh"),
        {"refresh": tokens["refresh"]},
        content_type="application/json",
    )
    assert refreshed.status_code == 200, refreshed.content
    new_refresh = refreshed.json()["refresh"]
    assert new_refresh != tokens["refresh"]

    # L'ancien refresh doit être mort : sinon un jeton intercepté reste
    # utilisable après rotation.
    replay = client.post(
        reverse("api-auth-refresh"),
        {"refresh": tokens["refresh"]},
        content_type="application/json",
    )
    assert replay.status_code == 401


@pytest.mark.django_db
def test_logout_revokes_the_refresh_token(client, user):
    tokens = client.post(
        reverse("api-auth-login"),
        {"email": user.email, "password": PASSWORD},
        content_type="application/json",
    ).json()

    logout = client.post(
        reverse("api-auth-logout"),
        {"refresh": tokens["refresh"]},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {tokens['access']}",
    )
    assert logout.status_code == 205

    replay = client.post(
        reverse("api-auth-refresh"),
        {"refresh": tokens["refresh"]},
        content_type="application/json",
    )
    assert replay.status_code == 401


@pytest.mark.django_db
def test_schema_is_served_and_describes_v1(client):
    response = client.get("/api/v1/schema/")
    assert response.status_code == 200
    assert b"openapi" in response.content[:200].lower()


@pytest.mark.django_db
def test_login_is_rate_limited(client, user):
    """Le bourrage d'identifiants doit être freiné.

    Le quota « auth » est de 10/min par défaut : la 11e tentative dans la
    minute doit être refusée, même avec un mot de passe correct.
    """
    url = reverse("api-auth-login")
    payload = {"email": user.email, "password": "mauvais-mot-de-passe"}

    statuses = [
        client.post(url, payload, content_type="application/json").status_code
        for _ in range(11)
    ]
    assert statuses[-1] == 429, statuses
    assert 429 not in statuses[:10], statuses
