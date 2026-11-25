from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from infrastructure.broker_clients import BrokerClientFactory


class BrokerConnectionService:
    @staticmethod
    @transaction.atomic
    def test_connection(broker_account):
        client = BrokerClientFactory.build(broker_account)
        try:
            payload = client.test_connection()
            broker_account.last_connection_status = True
            broker_account.last_connection_error = ""
            broker_account.last_connected_at = timezone.now()
            broker_account.status = "ACTIVE"
            broker_account.save(update_fields=[
                "last_connection_status",
                "last_connection_error",
                "last_connected_at",
                "status",
                "updated_at",
            ])
            return {"success": True, "payload": payload}
        except Exception as exc:
            from brokers.services_accounts import BrokerAccountService

            # Un broker peut renvoyer la valeur soumise dans son message
            # d'erreur. Ce champ est persisté puis servi par l'API : on le
            # nettoie avant écriture, pas à l'affichage.
            message = BrokerAccountService.redact_secrets(broker_account, str(exc))

            broker_account.last_connection_status = False
            broker_account.last_connection_error = message
            broker_account.last_connected_at = timezone.now()
            broker_account.status = "ERROR"
            broker_account.save(update_fields=[
                "last_connection_status",
                "last_connection_error",
                "last_connected_at",
                "status",
                "updated_at",
            ])
            return {"success": False, "error": message}


def build_deriv_client_for_account(broker_account):
    """
    Construit un DerivClient (WS one-shot) à partir d'un BrokerAccount.
    Retourne None si le compte n'est pas Deriv ou si le token est manquant.

    Utilisé par brokers.tasks_deriv_sync pour les sync ponctuelles.
    """
    from brokers.services.deriv import DerivClient

    if (broker_account.broker or "").upper() != "DERIV":
        return None
    token = broker_account.deriv_token
    app_id = (
        getattr(broker_account, "deriv_app_id", None)
        or getattr(broker_account, "deriv_client_id", None)
        or "1089"
    )
    if not token:
        return None
    return DerivClient(token=token, app_id=str(app_id))