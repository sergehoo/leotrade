"""
Phase 1 — création table BrokerExternalRef pour mapper les IDs
internes ↔ broker (Deriv contract_id, Binance orderId, MT5 ticket).
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("brokers", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="BrokerExternalRef",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "broker",
                    models.CharField(
                        choices=[
                            ("DERIV", "Deriv"),
                            ("BINANCE", "Binance"),
                            ("MT5", "MetaTrader 5"),
                        ],
                        db_index=True,
                        max_length=20,
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("CONTRACT", "Contract"),
                            ("ORDER", "Order"),
                            ("TRADE", "Trade"),
                            ("FILL", "Fill"),
                            ("TRANSACTION", "Transaction"),
                            ("POSITION", "Position"),
                        ],
                        db_index=True,
                        max_length=30,
                    ),
                ),
                ("external_id", models.CharField(db_index=True, max_length=120)),
                (
                    "internal_kind",
                    models.CharField(
                        choices=[
                            ("ORDER", "execution.Order"),
                            ("EXECUTION_FILL", "execution.ExecutionFill"),
                            ("POSITION", "portfolio.Position"),
                            ("TRADE", "portfolio.Trade"),
                        ],
                        db_index=True,
                        max_length=30,
                    ),
                ),
                ("internal_id", models.CharField(db_index=True, max_length=64)),
                ("last_status", models.CharField(blank=True, max_length=40)),
                ("last_payload", models.JSONField(blank=True, default=dict)),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "broker_account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="external_refs",
                        to="brokers.brokeraccount",
                    ),
                ),
            ],
            options={},
        ),
        migrations.AddConstraint(
            model_name="brokerexternalref",
            constraint=models.UniqueConstraint(
                fields=("broker", "kind", "external_id"),
                name="uniq_broker_external_ref",
            ),
        ),
        migrations.AddIndex(
            model_name="brokerexternalref",
            index=models.Index(
                fields=["internal_kind", "internal_id"],
                name="brokers_bro_interna_b50d8f_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="brokerexternalref",
            index=models.Index(
                fields=["broker_account", "kind"],
                name="brokers_bro_broker__c20e6f_idx",
            ),
        ),
    ]
