from __future__ import annotations

from typing import Optional

from django.db import transaction

from brokers.models import BrokerAccount, BrokerCredential
from brokers.models_constraints import BrokerConstraint
from infrastructure.broker_clients.gateway import BrokerGateway


class BrokerCredentialService:
    """
    Service de gestion des secrets broker.

    Compatible avec un BrokerAccount qui stocke `broker` comme simple string
    (ex: "BINANCE", "MT5", "DERIV"), sans enum TextChoices imbriqué.
    """

    REQUIRED_BY_BROKER = {
        "BINANCE": {
            "API_KEY",
            "API_SECRET",
        },
        "MT5": {
            "LOGIN",
            "PASSWORD",
            "SERVER",
        },
        "DERIV": {
            "TOKEN",
            "APP_ID",
        },
    }

    @classmethod
    @transaction.atomic
    def upsert_secret(
        cls,
        *,
        broker_account: BrokerAccount,
        secret_type: str,
        raw_value: str,
        created_by=None,
    ) -> BrokerCredential:
        secret_type = str(secret_type).upper().strip()

        credential, _ = BrokerCredential.objects.get_or_create(
            broker_account=broker_account,
            secret_type=secret_type,
            is_active=True,
            defaults={
                "created_by": created_by,
                "secret_value_encrypted": "",
            },
        )

        credential.created_by = created_by or credential.created_by

        # Compatible avec l'implémentation qu'on a construite plus tôt
        if hasattr(credential, "set_secret"):
            credential.set_secret(raw_value)
            update_fields = ["created_by", "secret_value_encrypted", "updated_at"]
        else:
            # fallback si ta classe n'a pas encore set_secret()
            from core.crypto import CryptoService
            credential.secret_value_encrypted = CryptoService.encrypt(raw_value)
            update_fields = ["created_by", "secret_value_encrypted", "updated_at"]

        credential.save(update_fields=update_fields)
        return credential

    @classmethod
    def get_secret(cls, broker_account: BrokerAccount, secret_type: str) -> Optional[str]:
        secret_type = str(secret_type).upper().strip()

        credential = broker_account.credentials.filter(
            secret_type=secret_type,
            is_active=True,
        ).first()

        if not credential:
            return None

        if hasattr(credential, "get_secret"):
            return credential.get_secret()

        if hasattr(credential, "get_secret_value"):
            return credential.get_secret_value()

        return None

    @classmethod
    def validate_required_credentials(cls, broker_account: BrokerAccount) -> None:
        broker_code = str(broker_account.broker or "").upper().strip()
        required = cls.REQUIRED_BY_BROKER.get(broker_code, set())

        existing = {
            str(x).upper().strip()
            for x in broker_account.credentials.filter(is_active=True).values_list("secret_type", flat=True)
        }

        missing = required - existing
        if missing:
            raise ValueError(
                f"Credentials manquants pour {broker_code}: {sorted(missing)}"
            )


class BrokerConstraintSyncService:
    @staticmethod
    @transaction.atomic
    def sync_symbol_constraint(broker_account: BrokerAccount, symbol: str):
        client = BrokerGateway(broker_account)
        dto = client.fetch_symbol_constraints(symbol)

        obj, _ = BrokerConstraint.objects.update_or_create(
            broker=str(broker_account.broker).upper().strip(),
            symbol=symbol,
            defaults={
                "min_qty": dto.min_qty,
                "max_qty": dto.max_qty,
                "qty_step": dto.qty_step,
                "min_notional": dto.min_notional,
                "price_tick": dto.price_tick,
                "leverage_min": dto.leverage_min,
                "leverage_max": dto.leverage_max,
                "contract_size": dto.contract_size,
                "raw_payload": dto.raw_payload,
            },
        )
        return obj
