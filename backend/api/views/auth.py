"""Authentification de l'API v1 (React / Flutter).

Parcours :
    POST /api/v1/auth/login/        email + mot de passe
        -> 200 {access, refresh, user}             si aucun MFA configuré
        -> 200 {mfa_required: true, mfa_token}     si un TOTP est actif
    POST /api/v1/auth/login/mfa/    mfa_token + code
        -> 200 {access, refresh, user}
    POST /api/v1/auth/refresh/      refresh -> nouveau couple (rotation)
    POST /api/v1/auth/logout/       refresh -> révocation (blacklist)
    GET  /api/v1/auth/me/           identité + KYC + capacités

Le jeton de défi MFA est une signature Django à durée de vie courte : il ne
porte aucune session, ne donne accès à rien, et ne peut être échangé que
contre un code valide. Il évite d'inventer un modèle de stockage pour un état
qui vit quelques dizaines de secondes.
"""

from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.core import signing
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from api.serializers.auth import (
    GENERIC_LOGIN_ERROR,
    LoginSerializer,
    LogoutSerializer,
    MFAChallengeSerializer,
    TokenPairSerializer,
    UserSerializer,
)

log = logging.getLogger("leotrade.api.auth")
User = get_user_model()

# Sel historique conservé malgré le renommage en LeoTrade : il signe les
# défis MFA en cours de validité. Le changer invaliderait, au moment du
# déploiement, les défis déjà envoyés aux utilisateurs en train de se
# connecter.
MFA_CHALLENGE_SALT = "lyneci.api.auth.mfa-challenge"
MFA_CHALLENGE_MAX_AGE = 300  # secondes


def _user_has_totp(user) -> bool:
    from allauth.mfa.models import Authenticator

    return Authenticator.objects.filter(
        user=user, type=Authenticator.Type.TOTP
    ).exists()


def _email_is_verified(user) -> bool:
    from allauth.account.models import EmailAddress

    return EmailAddress.objects.filter(
        user=user, email__iexact=user.email, verified=True
    ).exists()


def _issue_tokens(user, request) -> Response:
    refresh = RefreshToken.for_user(user)
    payload = {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "user": UserSerializer(user, context={"request": request}).data,
    }
    return Response(payload, status=status.HTTP_200_OK)


class LoginView(APIView):
    """Premier temps : vérification du mot de passe."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "auth"

    @extend_schema(
        request=LoginSerializer,
        responses={
            200: OpenApiResponse(
                response=TokenPairSerializer,
                description=(
                    "Couple de jetons, ou {mfa_required: true, mfa_token} "
                    "si un second facteur est configuré."
                ),
            ),
            400: OpenApiResponse(description="Identifiants invalides."),
            403: OpenApiResponse(description="Adresse email non vérifiée."),
        },
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]

        # L'email vérifié est obligatoire côté web (ACCOUNT_EMAIL_VERIFICATION
        # = "mandatory"). L'API ne doit pas offrir un chemin plus permissif.
        if not _email_is_verified(user):
            return Response(
                {
                    "detail": "Adresse email non vérifiée.",
                    "code": "EMAIL_NOT_VERIFIED",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if _user_has_totp(user):
            challenge = signing.dumps(
                {"user_id": user.pk}, salt=MFA_CHALLENGE_SALT
            )
            return Response(
                {
                    "mfa_required": True,
                    "mfa_token": challenge,
                    "expires_in": MFA_CHALLENGE_MAX_AGE,
                },
                status=status.HTTP_200_OK,
            )

        log.info("api.auth.login user_id=%s", user.pk)
        return _issue_tokens(user, request)


class LoginMFAView(APIView):
    """Second temps : validation du code TOTP ou d'un code de récupération."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "auth"

    @extend_schema(
        request=MFAChallengeSerializer,
        responses={
            200: OpenApiResponse(response=TokenPairSerializer),
            400: OpenApiResponse(description="Code invalide ou défi expiré."),
        },
    )
    def post(self, request):
        from allauth.mfa.models import Authenticator

        serializer = MFAChallengeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            data = signing.loads(
                serializer.validated_data["mfa_token"],
                salt=MFA_CHALLENGE_SALT,
                max_age=MFA_CHALLENGE_MAX_AGE,
            )
        except signing.SignatureExpired:
            return Response(
                {"detail": "Défi expiré, reprenez la connexion.", "code": "MFA_EXPIRED"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except signing.BadSignature:
            return Response(
                {"detail": GENERIC_LOGIN_ERROR}, status=status.HTTP_400_BAD_REQUEST
            )

        user = User.objects.filter(pk=data.get("user_id"), is_active=True).first()
        if user is None:
            return Response(
                {"detail": GENERIC_LOGIN_ERROR}, status=status.HTTP_400_BAD_REQUEST
            )

        code = serializer.validated_data["code"]
        # On essaie chaque authentificateur de l'utilisateur : TOTP d'abord,
        # puis codes de récupération. `validate_code` consomme le code de
        # récupération utilisé.
        authenticators = Authenticator.objects.filter(user=user).order_by("type")
        for authenticator in authenticators:
            try:
                if authenticator.wrap().validate_code(code):
                    log.info(
                        "api.auth.login.mfa user_id=%s type=%s",
                        user.pk,
                        authenticator.type,
                    )
                    return _issue_tokens(user, request)
            except Exception:  # pragma: no cover - dépend de l'implémentation allauth
                log.exception("api.auth.mfa.validate_failed user_id=%s", user.pk)

        log.warning("api.auth.login.mfa_rejected user_id=%s", user.pk)
        return Response(
            {"detail": "Code invalide.", "code": "MFA_INVALID"},
            status=status.HTTP_400_BAD_REQUEST,
        )


class LogoutView(APIView):
    """Révoque le refresh token.

    Sans blacklist, « se déconnecter » ne ferait qu'oublier le jeton côté
    client : il resterait utilisable jusqu'à expiration par quiconque l'a
    intercepté.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=LogoutSerializer,
        responses={205: OpenApiResponse(description="Jeton révoqué.")},
    )
    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            RefreshToken(serializer.validated_data["refresh"]).blacklist()
        except TokenError:
            # Jeton déjà expiré ou déjà révoqué : du point de vue de
            # l'appelant, la déconnexion a abouti.
            pass
        return Response(status=status.HTTP_205_RESET_CONTENT)


class MeView(APIView):
    """Identité de l'appelant, son état KYC et ses capacités."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: UserSerializer})
    def get(self, request):
        return Response(
            UserSerializer(request.user, context={"request": request}).data
        )
