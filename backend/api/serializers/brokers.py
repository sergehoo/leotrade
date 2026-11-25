"""
api/serializers/brokers.py
==========================

Contrat d'API des comptes broker.

Principe de base : un secret entre, il ne ressort jamais. Les quatre champs
de secret sont `write_only`, et la seule information rendue est leur
existence (`secrets`) plus la liste de ceux qui manquent encore
(`missing_secrets`), pour que l'interface puisse guider l'utilisateur sans
jamais réafficher une valeur.
"""

from __future__ import annotations

from rest_framework import serializers

from brokers.models import BrokerAccount, BrokerConstraint
from brokers.services_accounts import SECRET_FIELDS, BrokerAccountService


class SecretStateSerializer(serializers.Serializer):
    """État d'un secret : configuré ou non, et quand il a été posé."""

    configured = serializers.BooleanField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)
    rotated_at = serializers.DateTimeField(read_only=True, allow_null=True)


class BrokerAccountSerializer(serializers.ModelSerializer):
    # ── Secrets : entrée uniquement ────────────────────────────────────
    api_key = serializers.CharField(write_only=True, required=False, allow_blank=True, trim_whitespace=False)
    api_secret = serializers.CharField(write_only=True, required=False, allow_blank=True, trim_whitespace=False)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, trim_whitespace=False)
    deriv_token = serializers.CharField(write_only=True, required=False, allow_blank=True, trim_whitespace=False)

    # ── Secrets : sortie, métadonnées seulement ────────────────────────
    secrets = serializers.SerializerMethodField()
    missing_secrets = serializers.SerializerMethodField()
    required_secrets = serializers.SerializerMethodField()
    is_ready_to_connect = serializers.SerializerMethodField()

    class Meta:
        model = BrokerAccount
        fields = [
            "id", "name", "broker", "mode",
            "login", "server", "terminal_path",
            "deriv_app_id", "deriv_currency", "deriv_account_type",
            "is_active", "is_default", "status",
            "last_connection_status", "last_connection_error", "last_connected_at",
            "notes", "created_at", "updated_at",
            # Secrets (écriture)
            "api_key", "api_secret", "password", "deriv_token",
            # Secrets (lecture — métadonnées)
            "secrets", "missing_secrets", "required_secrets", "is_ready_to_connect",
        ]
        read_only_fields = [
            "status",
            "last_connection_status",
            "last_connection_error",
            "last_connected_at",
            "created_at",
            "updated_at",
        ]

    # ── Champs calculés ────────────────────────────────────────────────
    @staticmethod
    def get_secrets(obj) -> dict:
        return BrokerAccountService.secret_status(obj)

    @staticmethod
    def get_missing_secrets(obj) -> list:
        return BrokerAccountService.missing_secrets(obj)

    @staticmethod
    def get_required_secrets(obj) -> list:
        return list(BrokerAccountService.required_secrets(obj.broker))

    @staticmethod
    def get_is_ready_to_connect(obj) -> bool:
        return BrokerAccountService.is_ready_to_connect(obj)

    # ── Validation ─────────────────────────────────────────────────────
    def validate_name(self, value: str) -> str:
        """Unicité du nom par utilisateur, vérifiée avant l'IntegrityError.

        `unique_together` est posé sur (user, name), mais l'utilisateur
        n'est pas dans les données entrantes : DRF ne peut pas déduire la
        contrainte tout seul.
        """
        user = self.context["request"].user
        qs = BrokerAccount.objects.filter(user=user, name=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Tu as déjà un compte broker portant ce nom.")
        return value

    def validate(self, attrs: dict) -> dict:
        """Reporte les règles du modèle sur les bons champs du formulaire.

        `BrokerAccount.clean()` porte les exigences par broker (login/serveur
        pour MT5, app id pour Deriv). On les rejoue ici pour que l'erreur
        arrive sur le champ concerné plutôt qu'en 500 au moment du `save()`.
        """
        broker = attrs.get("broker") or getattr(self.instance, "broker", None)
        errors: dict[str, str] = {}

        def resolved(field):
            if field in attrs:
                return attrs[field]
            return getattr(self.instance, field, None)

        if broker == "MT5":
            if not resolved("login"):
                errors["login"] = "Login obligatoire pour MT5."
            if not resolved("server"):
                errors["server"] = "Serveur obligatoire pour MT5."

        if broker == "DERIV":
            if not resolved("deriv_app_id"):
                errors["deriv_app_id"] = "App ID obligatoire pour Deriv."
            if not resolved("deriv_currency"):
                errors["deriv_currency"] = "Devise Deriv obligatoire."

        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    # ── Découpage données / secrets ────────────────────────────────────
    @staticmethod
    def split_secrets(validated_data: dict) -> tuple[dict, dict]:
        """Sépare les secrets du reste : ils ne passent pas par le modèle."""
        secrets = {
            field: validated_data.pop(field)
            for field in list(SECRET_FIELDS)
            if field in validated_data
        }
        return validated_data, {k: v for k, v in secrets.items() if v}


class BrokerConstraintSerializer(serializers.ModelSerializer):
    """Contraintes d'instrument telles que publiées par le broker.

    `raw_payload` est volontairement exclu : c'est la réponse brute du
    broker, de forme non garantie, qui n'a pas à traverser le contrat
    d'API publique.
    """

    class Meta:
        model = BrokerConstraint
        fields = [
            "id", "broker", "symbol",
            "min_qty", "max_qty", "qty_step",
            "min_notional", "price_tick",
            "leverage_min", "leverage_max", "contract_size",
            "updated_at",
        ]
        read_only_fields = fields


class BrokerHealthSerializer(serializers.Serializer):
    """Santé opérationnelle d'un compte — lecture seule, aucune I/O broker."""

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    broker = serializers.CharField(read_only=True)
    mode = serializers.CharField(read_only=True)
    is_default = serializers.BooleanField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    status = serializers.CharField(read_only=True)
    connected = serializers.BooleanField(read_only=True)
    last_connected_at = serializers.DateTimeField(read_only=True, allow_null=True)
    last_error = serializers.CharField(read_only=True, allow_blank=True)
    circuit_state = serializers.CharField(read_only=True)
    last_sync_at = serializers.DateTimeField(read_only=True, allow_null=True)
    missing_secrets = serializers.ListField(child=serializers.CharField(), read_only=True)


class SyncConstraintSerializer(serializers.Serializer):
    """Entrée de la synchronisation des contraintes d'un instrument."""

    symbol = serializers.CharField(max_length=50)

    def validate_symbol(self, value: str) -> str:
        cleaned = (value or "").strip().upper()
        if not cleaned:
            raise serializers.ValidationError("Symbole requis.")
        return cleaned
