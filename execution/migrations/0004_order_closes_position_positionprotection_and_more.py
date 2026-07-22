from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("execution", "0003_alter_order_status_and_more"),
        ("portfolio", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="closes_position",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="closing_orders",
                to="portfolio.position",
            ),
        ),
        migrations.CreateModel(
            name="PositionProtection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("mode", models.CharField(choices=[("LOCAL_MONITORED", "Local monitored"), ("NATIVE_BROKER", "Native broker"), ("UNSUPPORTED", "Unsupported")], db_index=True, max_length=30)),
                ("status", models.CharField(choices=[("ACTIVE", "Active"), ("EXECUTING", "Executing"), ("COMPLETED", "Completed"), ("FAILED", "Failed"), ("DISABLED", "Disabled")], db_index=True, default="ACTIVE", max_length=20)),
                ("stop_loss", models.DecimalField(blank=True, decimal_places=8, max_digits=24, null=True)),
                ("take_profit", models.DecimalField(blank=True, decimal_places=8, max_digits=24, null=True)),
                ("trailing_enabled", models.BooleanField(default=False)),
                ("trail_percent", models.DecimalField(decimal_places=6, default=Decimal("0.015000"), max_digits=8)),
                ("atr", models.DecimalField(blank=True, decimal_places=8, max_digits=24, null=True)),
                ("atr_multiplier", models.DecimalField(decimal_places=4, default=Decimal("2.0000"), max_digits=8)),
                ("break_even_after_r", models.DecimalField(decimal_places=4, default=Decimal("1.0000"), max_digits=8)),
                ("high_watermark", models.DecimalField(blank=True, decimal_places=8, max_digits=24, null=True)),
                ("low_watermark", models.DecimalField(blank=True, decimal_places=8, max_digits=24, null=True)),
                ("last_price", models.DecimalField(blank=True, decimal_places=8, max_digits=24, null=True)),
                ("last_evaluated_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("triggered_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("trigger_reason", models.CharField(blank=True, max_length=40)),
                ("last_error", models.TextField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("close_order", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="position_protection", to="execution.order")),
                ("position", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="protection", to="portfolio.position")),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["mode", "status"], name="execution_p_mode_4a3258_idx"),
                    models.Index(fields=["status", "last_evaluated_at"], name="execution_p_status_22eeae_idx"),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.UniqueConstraint(
                condition=(
                    models.Q(("closes_position__isnull", False))
                    & models.Q(("status__in", ["PENDING_SUBMIT", "SUBMITTING", "UNKNOWN_BROKER_STATE", "SUBMITTED", "PARTIALLY_FILLED"]))
                ),
                fields=("closes_position",),
                name="uniq_active_close_order_position",
            ),
        ),
    ]
