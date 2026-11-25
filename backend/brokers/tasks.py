from celery import shared_task

from brokers.models import BrokerAccount
from brokers.services.base import BrokerConstraintSyncService
from brokers.services_connection import BrokerConnectionService
# from brokers.services_constraints import BrokerConstraintSyncService


@shared_task
def test_broker_connection_task(broker_account_id: int):
    broker = BrokerAccount.objects.filter(id=broker_account_id, is_active=True).first()
    if not broker:
        return {"status": "missing"}

    return BrokerConnectionService.test_connection(broker)


@shared_task
def sync_broker_constraint_task(broker_account_id: int, symbol: str):
    broker = BrokerAccount.objects.filter(id=broker_account_id, is_active=True).first()
    if not broker:
        return {"status": "missing"}

    constraint = BrokerConstraintSyncService.sync_symbol_constraint(broker, symbol)
    return {
        "status": "ok",
        "constraint_id": constraint.id,
        "symbol": constraint.symbol,
    }

@shared_task(name="brokers.tasks.check_all_brokers_health_task")
def check_all_brokers_health_task():
    """
    Health check périodique de tous les comptes broker actifs.

    Passe par le BrokerGateway (retry + circuit breaker) et persiste le
    résultat sur BrokerAccount (last_connection_status / error / at) —
    données affichées telles quelles par le Centre Broker.
    """
    import logging

    from django.utils import timezone

    from brokers.services_accounts import BrokerAccountService
    from infrastructure.broker_clients.gateway import BrokerGateway, CircuitOpenError

    logger = logging.getLogger("leotrade.brokers.health")

    checked = healthy = 0
    for account in BrokerAccount.objects.filter(is_active=True):
        checked += 1
        try:
            gateway = BrokerGateway(account)
            gateway.test_connection()
            account.last_connection_status = True
            account.last_connection_error = ""
            account.status = "ACTIVE"
            healthy += 1
        except CircuitOpenError as exc:
            account.last_connection_status = False
            account.last_connection_error = BrokerAccountService.redact_secrets(account, str(exc))
            account.status = "ERROR"
        except Exception as exc:
            account.last_connection_status = False
            # Même filtre que le test manuel : un health check ne doit pas
            # devenir le chemin par lequel un secret est persisté en clair.
            account.last_connection_error = BrokerAccountService.redact_secrets(
                account, str(exc),
            )[:2000]
            account.status = "ERROR"
            logger.warning(
                "broker.health_check_failed account_id=%s broker=%s error=%s",
                account.pk, account.broker, exc,
            )
        account.last_connected_at = timezone.now()
        account.save(update_fields=[
            "last_connection_status", "last_connection_error",
            "last_connected_at", "status", "updated_at",
        ])

    return {"checked": checked, "healthy": healthy}


# Celery autodiscover n'importe que <app>.tasks : on importe explicitement le
# module annexe pour que ses tâches (sync_deriv_balance_task, etc.) soient
# enregistrées dans le worker — sinon "Received unregistered task".
from brokers import tasks_deriv_sync  # noqa: E402,F401
