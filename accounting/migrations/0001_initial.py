"""
Phase 2 — création de l'app accounting et de la table Transfer.
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("portfolio", "0001_initial"),
        ("wallet", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Transfer",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "request_id",
                    models.CharField(
                        db_index=True,
                        help_text="Idempotency key fournie par le caller (UUID).",
                        max_length=120,
                        unique=True,
                    ),
                ),
                (
                    "direction",
                    models.CharField(
                        choices=[
                            ("WALLET_TO_PORTFOLIO", "Wallet → Portfolio"),
                            ("PORTFOLIO_TO_WALLET", "Portfolio → Wallet"),
                        ],
                        max_length=30,
                    ),
                ),
                ("amount", models.DecimalField(decimal_places=2, max_digits=18)),
                ("currency", models.CharField(default="USD", max_length=10)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("COMPLETED", "Completed"),
                            ("FAILED", "Failed"),
                            ("REVERTED", "Reverted"),
                        ],
                        db_index=True,
                        default="PENDING",
                        max_length=20,
                    ),
                ),
                ("error_message", models.TextField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="accounting_transfers",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "wallet",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="accounting_transfers",
                        to="wallet.wallet",
                    ),
                ),
                (
                    "portfolio",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="accounting_transfers",
                        to="portfolio.portfolio",
                    ),
                ),
                (
                    "wallet_ledger_entry",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="wallet.walletledgerentry",
                    ),
                ),
                (
                    "portfolio_ledger_entry",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="portfolio.cashledgerentry",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="transfer",
            index=models.Index(fields=["user", "status"], name="accounting__user_id_a78fce_idx"),
        ),
        migrations.AddIndex(
            model_name="transfer",
            index=models.Index(fields=["wallet", "status"], name="accounting__wallet__c10b09_idx"),
        ),
        migrations.AddIndex(
            model_name="transfer",
            index=models.Index(fields=["portfolio", "status"], name="accounting__portfol_e4d520_idx"),
        ),
    ]
