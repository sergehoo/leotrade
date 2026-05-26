"""
brokers/models_external_ref.py
==============================

Mapping IDs internes ↔ IDs broker externes, générique pour
Deriv (contract_id, transaction_id), Binance (orderId, tradeId)
et MT5 (ticket).

Cette table est la *source unique* pour retrouver la correspondance
entre une entité interne (Order, ExecutionFill, Position, Trade)
et son pendant côté broker.

Idempotence garantie par UNIQUE(broker, kind, external_id).
"""

from __future__ import annotations

from django.db import models


class BrokerExternalRef(models.Model):
    """
    Une référence externe broker.

    Exemples :
        broker="DERIV", kind="CONTRACT",     external_id="123456789"
            → internal_kind="ORDER", internal_id="42"
        broker="DERIV", kind="TRANSACTION",  external_id="987654321"
            → internal_kind="EXECUTION_FILL", internal_id="17"
        broker="BINANCE", kind="ORDER",       external_id="b-1234"
            → internal_kind="ORDER", internal_id="42"
        broker="BINANCE", kind="TRADE",       external_id="t-9876"
            → internal_kind="EXECUTION_FILL", internal_id="17"
    """

    BROKER_CHOICES = [
        ("DERIV", "Deriv"),
        ("BINANCE", "Binance"),
        ("MT5", "MetaTrader 5"),
    ]

    KIND_CHOICES = [
        ("CONTRACT", "Contract"),
        ("ORDER", "Order"),
        ("TRADE", "Trade"),
        ("FILL", "Fill"),
        ("TRANSACTION", "Transaction"),
        ("POSITION", "Position"),
    ]

    INTERNAL_KIND_CHOICES = [
        ("ORDER", "execution.Order"),
        ("EXECUTION_FILL", "execution.ExecutionFill"),
        ("POSITION", "portfolio.Position"),
        ("TRADE", "portfolio.Trade"),
    ]

    broker = models.CharField(max_length=20, choices=BROKER_CHOICES, db_index=True)
    broker_account = models.ForeignKey(
        "brokers.BrokerAccount",
        on_delete=models.CASCADE,
        related_name="external_refs",
    )
    kind = models.CharField(max_length=30, choices=KIND_CHOICES, db_index=True)
    external_id = models.CharField(max_length=120, db_index=True)

    internal_kind = models.CharField(max_length=30, choices=INTERNAL_KIND_CHOICES, db_index=True)
    internal_id = models.CharField(max_length=64, db_index=True)

    # Snapshot léger du dernier statut connu côté broker (pour debug rapide)
    last_status = models.CharField(max_length=40, blank=True)
    last_payload = models.JSONField(default=dict, blank=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["broker", "kind", "external_id"],
                name="uniq_broker_external_ref",
            ),
        ]
        indexes = [
            models.Index(fields=["internal_kind", "internal_id"]),
            models.Index(fields=["broker_account", "kind"]),
        ]

    def __str__(self):
        return f"{self.broker}/{self.kind}/{self.external_id} → {self.internal_kind}/{self.internal_id}"

    @classmethod
    def upsert(
        cls,
        *,
        broker: str,
        broker_account,
        kind: str,
        external_id: str,
        internal_kind: str,
        internal_id: str | int,
        last_status: str = "",
        last_payload: dict | None = None,
    ) -> "BrokerExternalRef":
        """
        Crée ou met à jour la référence. Idempotent sur (broker, kind, external_id).
        """
        obj, _created = cls.objects.update_or_create(
            broker=broker,
            kind=kind,
            external_id=str(external_id),
            defaults={
                "broker_account": broker_account,
                "internal_kind": internal_kind,
                "internal_id": str(internal_id),
                "last_status": last_status or "",
                "last_payload": last_payload or {},
            },
        )
        return obj

    @classmethod
    def resolve(cls, *, broker: str, kind: str, external_id: str) -> "BrokerExternalRef | None":
        """
        Retourne la ref si elle existe, sans erreur sinon.
        """
        return cls.objects.filter(
            broker=broker,
            kind=kind,
            external_id=str(external_id),
        ).first()
