"""
Phase 3 — création de la table Trade (round-trip clos).
"""

from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("portfolio", "0001_initial"),
        ("brokers", "0002_broker_external_ref"),
        ("execution", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Trade",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("broker_fill_id", models.CharField(blank=True, db_index=True, max_length=120, null=True)),
                ("symbol", models.CharField(db_index=True, max_length=50)),
                (
                    "side",
                    models.CharField(
                        choices=[("LONG", "Long"), ("SHORT", "Short")],
                        max_length=10,
                    ),
                ),
                ("quantity", models.DecimalField(decimal_places=8, max_digits=24)),
                ("entry_avg_price", models.DecimalField(decimal_places=8, max_digits=24)),
                ("exit_avg_price", models.DecimalField(decimal_places=8, max_digits=24)),
                (
                    "gross_pnl",
                    models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=18),
                ),
                (
                    "fees",
                    models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=18),
                ),
                ("realized_pnl", models.DecimalField(decimal_places=2, max_digits=18)),
                (
                    "cash_invested",
                    models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=18),
                ),
                (
                    "cash_returned",
                    models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=18),
                ),
                ("opened_at", models.DateTimeField(db_index=True)),
                ("closed_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "broker_account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="trades",
                        to="brokers.brokeraccount",
                    ),
                ),
                (
                    "closing_fill",
                    models.ForeignKey(
                        blank=True, null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="closes_trade",
                        to="execution.executionfill",
                    ),
                ),
                (
                    "opening_order",
                    models.ForeignKey(
                        blank=True, null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="opening_trades",
                        to="execution.order",
                    ),
                ),
                (
                    "portfolio",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="trades",
                        to="portfolio.portfolio",
                    ),
                ),
                (
                    "position",
                    models.ForeignKey(
                        blank=True, null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="trades",
                        to="portfolio.position",
                    ),
                ),
            ],
            options={
                "ordering": ["-closed_at"],
            },
        ),
        migrations.AddIndex(
            model_name="trade",
            index=models.Index(
                fields=["portfolio", "closed_at"],
                name="portfolio_t_portfol_a3b1c2_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="trade",
            index=models.Index(
                fields=["portfolio", "symbol"],
                name="portfolio_t_portfol_e90df3_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="trade",
            index=models.Index(
                fields=["broker_account"],
                name="portfolio_t_broker__c4ee21_idx",
            ),
        ),
    ]
