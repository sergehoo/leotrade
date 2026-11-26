import logging

from django.db import models
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from core.models import TimeStampedModel
from core.crypto import CryptoService

User = get_user_model()

# Audit des accès aux secrets : chaque décryptage est journalisé (qui/quoi/quand
# via le contexte de requête structuré — jamais la valeur elle-même).
secret_access_log = logging.getLogger("leotrade.brokers.secret_access")


class BrokerAccount(TimeStampedModel):
    BROKER_CHOICES = [
        ("BINANCE", "Binance"),
        ("MT5", "MetaTrader 5"),
        ("DERIV", "Deriv"),
        # Place d'exécution locale : aucun compte distant, aucun
        # identifiant, aucun appel réseau. Elle existe pour que le mode
        # simulation soit utilisable sans ouvrir de compte chez un courtier
        # — c'est le point d'entrée de la plateforme.
        #
        # Le routage d'exécution se fait sur `mode` (cf.
        # execution.adapters.factory), donc un compte SIMULATION en mode
        # PAPER emprunte le PaperBrokerAdapter comme n'importe quel autre.
        # Il ne peut pas passer en LIVE : voir `clean()`.
        ("SIMULATION", "Simulation"),
    ]

    MODE_CHOICES = [
        ("PAPER", "Paper"),
        ("LIVE", "Live"),
    ]

    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("ACTIVE", "Active"),
        ("INACTIVE", "Inactive"),
        ("ERROR", "Error"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="broker_accounts")
    name = models.CharField(max_length=150)
    broker = models.CharField(max_length=20, choices=BROKER_CHOICES, db_index=True)
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default="PAPER", db_index=True)

    login = models.CharField(max_length=100, blank=True, null=True)
    server = models.CharField(max_length=255, blank=True, null=True)
    terminal_path = models.CharField(max_length=500, blank=True, null=True)

    deriv_app_id = models.CharField(max_length=50, blank=True, null=True)
    deriv_currency = models.CharField(max_length=10, default="USD")
    deriv_account_type = models.CharField(max_length=50, blank=True, null=True)

    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="DRAFT")

    last_connection_status = models.BooleanField(default=False)
    last_connection_error = models.TextField(blank=True, null=True)
    last_connected_at = models.DateTimeField(blank=True, null=True)

    notes = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = [("user", "name")]
        ordering = ["name"]
        indexes = [
            models.Index(fields=["user", "broker"]),
            models.Index(fields=["user", "is_default"]),
            models.Index(fields=["user", "is_active"]),
        ]

    def __str__(self):
        return f"{self.user} - {self.name} ({self.broker}/{self.mode})"

    def clean(self):
        errors = {}

        if self.is_default:
            qs = BrokerAccount.objects.filter(user=self.user, is_default=True)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                errors["is_default"] = "Un seul broker par utilisateur peut être défini par défaut."

        if self.broker == "MT5":
            if not self.login:
                errors["login"] = "Login obligatoire pour MT5."
            if not self.server:
                errors["server"] = "Serveur obligatoire pour MT5."

        if self.broker == "DERIV":
            if not self.deriv_app_id:
                errors["deriv_app_id"] = "App ID obligatoire pour Deriv."
            if not self.deriv_currency:
                errors["deriv_currency"] = "Devise Deriv obligatoire."

        if self.broker == "SIMULATION" and self.mode == "LIVE":
            # Il n'y a rien derrière : un ordre « réel » sur une place
            # locale n'atteindrait aucun marché tout en portant le libellé
            # qui fait baisser la garde de l'utilisateur.
            errors["mode"] = (
                "Un compte de simulation ne peut pas être passé en mode réel : "
                "aucun marché n'est derrière. Connecte un vrai broker pour "
                "trader en réel."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def set_secret(self, secret_type: str, value: str, created_by=None):
        encrypted = CryptoService.encrypt(value)
        obj, _ = BrokerCredential.objects.update_or_create(
            broker_account=self,
            secret_type=secret_type,
            defaults={
                "secret_value_encrypted": encrypted,
                "is_active": True,
                "created_by": created_by,
            },
        )
        return obj

    def get_secret(self, secret_type: str) -> str:
        cred = self.credentials.filter(secret_type=secret_type, is_active=True).order_by("-created_at").first()
        if not cred:
            return ""
        return cred.get_secret_value()

    @property
    def api_key(self) -> str:
        return self.get_secret("API_KEY")

    @property
    def api_secret(self) -> str:
        return self.get_secret("API_SECRET")

    @property
    def password(self) -> str:
        return self.get_secret("PASSWORD")

    @property
    def deriv_token(self) -> str:
        return self.get_secret("DERIV_TOKEN")


class BrokerCredential(TimeStampedModel):
    SECRET_TYPE_CHOICES = [
        ("API_KEY", "API Key"),
        ("API_SECRET", "API Secret"),
        ("PASSWORD", "Password"),
        ("DERIV_TOKEN", "Deriv Token"),
    ]

    broker_account = models.ForeignKey(
        BrokerAccount,
        on_delete=models.CASCADE,
        related_name="credentials",
    )
    secret_type = models.CharField(max_length=30, choices=SECRET_TYPE_CHOICES)
    secret_value_encrypted = models.TextField()
    key_version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_broker_credentials",
    )
    rotated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["broker_account", "secret_type", "is_active"]),
        ]

    def __str__(self):
        return f"{self.broker_account.name} - {self.secret_type}"

    def get_secret_value(self) -> str:
        # Audit trail : trace l'accès (jamais la valeur déchiffrée).
        secret_access_log.info(
            "credential.decrypted",
            extra={
                "event": "credential.decrypted",
                "credential_id": self.pk,
                "broker_account_id": self.broker_account_id,
                "secret_type": self.secret_type,
                "key_version": self.key_version,
            },
        )
        return CryptoService.decrypt(self.secret_value_encrypted)

from .models_constraints import BrokerConstraint

# Phase 1 — mapping interne ↔ broker. Cet import garantit que Django
# découvre le modèle au chargement de l'app (sinon makemigrations le supprime).
from brokers.models_external_ref import BrokerExternalRef  # noqa: E402,F401
