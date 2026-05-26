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