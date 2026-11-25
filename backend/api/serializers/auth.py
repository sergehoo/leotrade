"""Sérialiseurs d'authentification de l'API v1.

Contraintes reprises du socle web existant et à ne pas affaiblir :
- `ACCOUNT_LOGIN_METHODS = {"email"}` : on s'authentifie par email, pas par
  username.
- `ACCOUNT_EMAIL_VERIFICATION = "mandatory"` : un email non vérifié ne doit
  pas obtenir de jeton.
- `ACCOUNT_PREVENT_ENUMERATION = True` : les erreurs ne révèlent jamais si
  l'adresse existe.
- `allauth.mfa` est actif (TOTP + codes de récupération). Délivrer un JWT sur
  la seule paire email/mot de passe contournerait le second facteur : la
  connexion est donc en deux temps lorsqu'un authentificateur existe.
"""

from __future__ import annotations

from django.contrib.auth import authenticate, get_user_model
from rest_framework import serializers

User = get_user_model()

# Message unique pour tout échec de connexion : identifiants inconnus,
# mot de passe faux ou compte désactivé produisent la même réponse.
GENERIC_LOGIN_ERROR = "Identifiants invalides."


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        email = attrs["email"].strip().lower()
        password = attrs["password"]

        # `authenticate` passe par les backends configurés (allauth gère la
        # résolution email -> user). On ne cherche jamais l'utilisateur à la
        # main : cela réintroduirait une fuite par timing.
        user = authenticate(
            request=self.context.get("request"),
            username=email,
            password=password,
        )
        if user is None:
            raise serializers.ValidationError({"detail": GENERIC_LOGIN_ERROR})
        if not user.is_active:
            raise serializers.ValidationError({"detail": GENERIC_LOGIN_ERROR})

        attrs["user"] = user
        return attrs


class MFAChallengeSerializer(serializers.Serializer):
    """Second temps de la connexion : jeton de défi + code à usage unique."""

    mfa_token = serializers.CharField()
    code = serializers.CharField(min_length=6, max_length=12, trim_whitespace=True)


class UserSerializer(serializers.ModelSerializer):
    """Identité renvoyée par /auth/me/.

    N'expose que ce dont les clients ont besoin pour décider d'un affichage.
    Aucun secret, aucune clé broker, aucun identifiant de document KYC.
    """

    kyc_status = serializers.SerializerMethodField()
    kyc_rejection_reason = serializers.SerializerMethodField()
    mfa_enabled = serializers.SerializerMethodField()
    email_verified = serializers.SerializerMethodField()
    capabilities = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "date_joined",
            "last_login",
            "is_staff",
            "kyc_status",
            "kyc_rejection_reason",
            "mfa_enabled",
            "email_verified",
            "capabilities",
        ]
        read_only_fields = fields

    def get_kyc_status(self, obj) -> str:
        profile = getattr(obj, "kyc_profile", None)
        return profile.status if profile else "NOT_STARTED"

    def get_kyc_rejection_reason(self, obj) -> str:
        profile = getattr(obj, "kyc_profile", None)
        if profile and profile.status == "REJECTED":
            return profile.rejection_reason or ""
        return ""

    def get_mfa_enabled(self, obj) -> bool:
        from allauth.mfa.models import Authenticator

        return Authenticator.objects.filter(
            user=obj, type=Authenticator.Type.TOTP
        ).exists()

    def get_email_verified(self, obj) -> bool:
        from allauth.account.models import EmailAddress

        return EmailAddress.objects.filter(
            user=obj, email__iexact=obj.email, verified=True
        ).exists()

    def get_capabilities(self, obj) -> dict:
        """Ce que l'utilisateur a le droit de faire, calculé côté serveur.

        Le client s'en sert pour griser une action — jamais pour l'autoriser.
        L'autorisation réelle reste vérifiée à chaque appel d'écriture.
        """
        profile = getattr(obj, "kyc_profile", None)
        kyc_approved = bool(profile and profile.status == "APPROVED")
        return {
            # Le trading réel exige un KYC validé (décision d'architecture
            # enregistrée : live-trading-requires-approved-kyc).
            "can_trade_live": kyc_approved,
            "can_trade_paper": True,
            "can_withdraw": kyc_approved,
            "kyc_required_for": ["LIVE_TRADING", "WITHDRAWAL"],
        }


class TokenPairSerializer(serializers.Serializer):
    """Forme de la réponse d'authentification réussie (documentation OpenAPI)."""

    access = serializers.CharField()
    refresh = serializers.CharField()
    user = UserSerializer()


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()
