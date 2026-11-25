"""
brokers/services_accounts.py
============================

Logique métier du cycle de vie d'un compte broker, centralisée ici pour que
l'API REST (React / Flutter) et les vues Django historiques partagent
exactement les mêmes règles — pas de duplication, pas de divergence.

Règles non négociables appliquées ici :

  - Un secret broker n'est JAMAIS relu ni renvoyé. On n'expose que son
    existence et sa date de rotation (`secret_status`).
  - Le passage d'un compte en mode LIVE exige un KYC approuvé
    (`assert_live_allowed`). Le retour en PAPER est toujours autorisé :
    la porte de sortie ne se verrouille pas.
  - Un seul compte par défaut et par utilisateur, garanti par une
    transaction et un verrou de ligne, pas par un simple `update()`.
  - On ne supprime pas un compte qui porte encore des positions ouvertes.
"""

from __future__ import annotations

import logging
from typing import Iterable, Mapping

from django.db import transaction

log = logging.getLogger("lyneci.brokers.accounts")


# Champ d'entrée (clair, write-only) → type de secret stocké chiffré.
SECRET_FIELDS: dict[str, str] = {
    "api_key": "API_KEY",
    "api_secret": "API_SECRET",
    "password": "PASSWORD",
    "deriv_token": "DERIV_TOKEN",
}

# Secrets sans lesquels une connexion réelle ne peut pas aboutir.
# Sert à prévenir l'utilisateur AVANT qu'il tente un test de connexion,
# pas à bloquer la création (un compte peut être préparé en brouillon).
REQUIRED_SECRETS: dict[str, tuple[str, ...]] = {
    "BINANCE": ("api_key", "api_secret"),
    "MT5": ("password",),
    "DERIV": ("deriv_token",),
}


class BrokerAccountError(Exception):
    """Erreur métier sur un compte broker, porteuse d'un code stable."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class LiveModeNotAllowed(BrokerAccountError):
    """Mode LIVE refusé : KYC non approuvé."""


class BrokerAccountService:
    # ------------------------------------------------------------------
    # Secrets — existence seulement, jamais la valeur
    # ------------------------------------------------------------------
    @staticmethod
    def secret_status(account) -> dict[str, dict]:
        """État des secrets d'un compte, sans aucune valeur déchiffrée.

        On lit les métadonnées en base (pas `get_secret`) : aucun appel à
        `CryptoService.decrypt`, donc aucune entrée dans le journal d'accès
        aux secrets pour un simple affichage d'écran.
        """
        rows = account.credentials.filter(is_active=True).values(
            "secret_type", "updated_at", "rotated_at",
        )
        by_type = {row["secret_type"]: row for row in rows}

        status: dict[str, dict] = {}
        for field, secret_type in SECRET_FIELDS.items():
            row = by_type.get(secret_type)
            status[field] = {
                "configured": row is not None,
                "updated_at": row["updated_at"] if row else None,
                "rotated_at": row["rotated_at"] if row else None,
            }
        return status

    @staticmethod
    def required_secrets(broker: str) -> tuple[str, ...]:
        return REQUIRED_SECRETS.get((broker or "").upper(), ())

    @classmethod
    def missing_secrets(cls, account) -> list[str]:
        """Secrets requis par le broker mais pas encore enregistrés."""
        configured = {
            field
            for field, state in cls.secret_status(account).items()
            if state["configured"]
        }
        return [
            field
            for field in cls.required_secrets(account.broker)
            if field not in configured
        ]

    @classmethod
    def is_ready_to_connect(cls, account) -> bool:
        return not cls.missing_secrets(account)

    @staticmethod
    def _store_secrets(account, secrets: Mapping[str, str], actor=None) -> list[str]:
        """Chiffre et enregistre les secrets fournis. Renvoie ceux qui ont changé.

        Une valeur vide ou absente conserve le secret existant — c'est ce qui
        permet de modifier un compte sans ressaisir ses clés.
        """
        stored = []
        for field, secret_type in SECRET_FIELDS.items():
            value = (secrets or {}).get(field)
            if not value:
                continue
            account.set_secret(secret_type, value, created_by=actor)
            stored.append(field)
        if stored:
            log.info(
                "broker.secrets_stored account_id=%s broker=%s fields=%s",
                account.pk, account.broker, ",".join(sorted(stored)),
            )
        return stored

    # ------------------------------------------------------------------
    # Garde KYC sur le mode LIVE
    # ------------------------------------------------------------------
    @staticmethod
    def assert_live_allowed(user) -> None:
        """Interdit le mode LIVE tant que le KYC n'est pas approuvé.

        Garde unique partagée par l'API et les vues Django : le mode LIVE
        est le seul interrupteur qui expose de l'argent réel, il ne doit
        pas dépendre de l'écran par lequel on l'actionne.
        """
        profile = getattr(user, "kyc_profile", None)
        current = getattr(profile, "status", None)
        if current == "APPROVED":
            return
        raise LiveModeNotAllowed(
            "KYC_REQUIRED",
            "Ton dossier KYC doit être approuvé avant d'activer le mode LIVE. "
            "Le mode PAPER reste disponible sans restriction.",
        )

    @classmethod
    def assert_mode_allowed(cls, user, mode: str) -> None:
        if (mode or "").upper() == "LIVE":
            cls.assert_live_allowed(user)

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------
    @classmethod
    @transaction.atomic
    def create_account(cls, user, *, data: Mapping, secrets: Mapping | None = None):
        from brokers.models import BrokerAccount

        cls.assert_mode_allowed(user, data.get("mode"))

        account = BrokerAccount(user=user, **dict(data))
        if not account.status:
            account.status = "DRAFT"

        # Rétrograder AVANT d'enregistrer : `BrokerAccount.save()` appelle
        # `full_clean()`, qui refuse un second compte par défaut. Le faire
        # après lèverait une ValidationError sur une création légitime.
        if account.is_default:
            cls._demote_other_defaults(user, account)

        account.save()

        cls._store_secrets(account, secrets or {}, actor=user)

        cls._notify(
            user, "BROKER_ACCOUNT_CREATED",
            title=f"Compte broker créé : {account.name}",
            message=f"Compte {account.broker} « {account.name} » créé en mode {account.mode}.",
            payload={"broker_account_id": account.pk, "broker": account.broker, "mode": account.mode},
        )
        return account

    @classmethod
    @transaction.atomic
    def update_account(cls, account, *, data: Mapping, secrets: Mapping | None = None, actor=None):
        new_mode = data.get("mode", account.mode)
        if (new_mode or "").upper() == "LIVE" and account.mode != "LIVE":
            cls.assert_live_allowed(account.user)

        for field, value in dict(data).items():
            setattr(account, field, value)

        if account.is_default:
            cls._demote_other_defaults(account.user, account)

        account.save()

        cls._store_secrets(account, secrets or {}, actor=actor or account.user)

        cls._notify(
            account.user, "BROKER_ACCOUNT_UPDATED",
            title=f"Compte broker modifié : {account.name}",
            message=f"La configuration du compte {account.broker} « {account.name} » a été modifiée.",
            payload={"broker_account_id": account.pk, "broker": account.broker, "mode": account.mode},
        )
        return account

    @staticmethod
    def _demote_other_defaults(user, account) -> None:
        from brokers.models import BrokerAccount

        qs = BrokerAccount.objects.filter(user=user, is_default=True)
        if account.pk:
            qs = qs.exclude(pk=account.pk)
        qs.update(is_default=False)

    @classmethod
    @transaction.atomic
    def set_default(cls, user, account):
        """Désigne le compte par défaut de l'utilisateur.

        `select_for_update` sérialise deux requêtes concurrentes : sans lui,
        deux appels simultanés peuvent laisser zéro ou deux comptes par
        défaut, et `BrokerAccount.clean()` rejetterait alors toute écriture
        ultérieure sur le compte.
        """
        from brokers.models import BrokerAccount

        list(
            BrokerAccount.objects
            .select_for_update()
            .filter(user=user)
            .order_by("pk")
            .values_list("pk", flat=True)
        )

        BrokerAccount.objects.filter(user=user, is_default=True).update(is_default=False)
        BrokerAccount.objects.filter(pk=account.pk).update(is_default=True)
        account.refresh_from_db()

        cls._notify(
            user, "BROKER_DEFAULT_CHANGED",
            title=f"Broker par défaut : {account.name}",
            message=(
                f"« {account.name} » ({account.broker}, mode {account.mode}) "
                f"est maintenant ton broker par défaut."
            ),
            payload={"broker_account_id": account.pk, "broker": account.broker, "mode": account.mode},
        )
        return account

    @staticmethod
    def assert_deletable(account) -> None:
        """Refuse la suppression d'un compte encore engagé sur le marché.

        `Position.on_delete=CASCADE` : supprimer le compte effacerait
        silencieusement l'historique des positions et les portefeuilles qui
        s'y rattachent. On préfère refuser et proposer la désactivation.
        """
        open_positions = account.positions.filter(status="OPEN").count()
        if open_positions:
            raise BrokerAccountError(
                "OPEN_POSITIONS",
                f"Ce compte porte {open_positions} position(s) ouverte(s). "
                f"Ferme-les ou désactive le compte au lieu de le supprimer.",
            )

        portfolios = account.portfolios.count() if hasattr(account, "portfolios") else 0
        if portfolios:
            raise BrokerAccountError(
                "LINKED_PORTFOLIOS",
                f"Ce compte est rattaché à {portfolios} portefeuille(s). "
                f"Sa suppression effacerait leur historique — désactive-le à la place.",
            )

    # ------------------------------------------------------------------
    # Test de connexion
    # ------------------------------------------------------------------
    @classmethod
    def test_connection(cls, account) -> dict:
        """Teste la connexion réelle, persiste l'état et notifie.

        Centralisé ici pour que l'API et les tâches Celery produisent la
        même trace : sans cela, un test lancé depuis l'app mobile
        n'émettrait aucune notification alors qu'un health check en
        émettrait une.
        """
        if cls.missing_secrets(account):
            raise BrokerAccountError(
                "MISSING_SECRETS",
                "Identifiants incomplets pour ce broker : connexion impossible.",
            )

        from brokers.services_connection import BrokerConnectionService

        result = BrokerConnectionService.test_connection(account)
        account.refresh_from_db()

        if result["success"]:
            cls._notify(
                account.user, "BROKER_CONNECTION_OK",
                title=f"Connexion broker réussie : {account.name}",
                message=f"Le test de connexion à {account.broker} « {account.name} » a réussi.",
                payload={"broker_account_id": account.pk, "broker": account.broker},
            )
        else:
            error = result.get("error") or "erreur inconnue"
            cls._notify(
                account.user, "BROKER_CONNECTION_FAILED",
                title=f"Connexion broker échouée : {account.name}",
                message=(
                    f"Le test de connexion à {account.broker} « {account.name} » a échoué : "
                    f"{error}. Vérifie tes identifiants."
                ),
                payload={
                    "broker_account_id": account.pk,
                    "broker": account.broker,
                    "error": str(error)[:500],
                },
            )
        return result

    # ------------------------------------------------------------------
    # Santé du parc broker
    # ------------------------------------------------------------------
    @staticmethod
    def health(accounts: Iterable) -> list[dict]:
        """État opérationnel réel de chaque compte : connexion, circuit, sync.

        Aucune I/O broker n'est déclenchée ici — on lit l'état persisté par
        les health checks Celery et le circuit breaker partagé.
        """
        from brokers.models_external_ref import BrokerExternalRef
        from infrastructure.broker_clients.gateway import BrokerGateway

        rows = []
        for account in accounts:
            # `client=object()` : le gateway ne doit pas construire de client
            # réel pour une simple lecture de l'état du circuit.
            circuit = BrokerGateway(account, client=object()).circuit_state()

            last_sync = (
                BrokerExternalRef.objects
                .filter(broker_account=account)
                .order_by("-last_seen_at")
                .values_list("last_seen_at", flat=True)
                .first()
            )

            rows.append({
                "id": account.pk,
                "name": account.name,
                "broker": account.broker,
                "mode": account.mode,
                "is_default": account.is_default,
                "is_active": account.is_active,
                "status": account.status,
                "connected": bool(account.last_connection_status),
                "last_connected_at": account.last_connected_at,
                "last_error": account.last_connection_error or "",
                "circuit_state": circuit,
                "last_sync_at": last_sync,
                "missing_secrets": BrokerAccountService.missing_secrets(account),
            })
        return rows

    # ------------------------------------------------------------------
    @staticmethod
    def _notify(user, event_type: str, **kwargs):
        """Notification best-effort : une notif qui échoue ne casse rien."""
        from notifications.shortcuts import notify

        return notify(user, event_type, **kwargs)
