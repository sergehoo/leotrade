from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


def normalize_existing_runs(apps, schema_editor):
    BacktestRun = apps.get_model("leo_backtesting", "BacktestRun")
    BacktestRun.objects.filter(initial_cash__lte=0).update(initial_cash=Decimal("0.01"))
    BacktestRun.objects.filter(commission__lt=0).update(commission=Decimal("0"))
    BacktestRun.objects.filter(commission__gt=Decimal("0.10")).update(
        commission=Decimal("0.10")
    )
    BacktestRun.objects.filter(spread__lt=0).update(spread=Decimal("0"))
    BacktestRun.objects.filter(spread__gt=Decimal("0.05")).update(spread=Decimal("0.05"))
    BacktestRun.objects.filter(slippage__lt=0).update(slippage=Decimal("0"))
    BacktestRun.objects.filter(slippage__gt=Decimal("0.05")).update(
        slippage=Decimal("0.05")
    )
    BacktestRun.objects.filter(end_date__lt=models.F("start_date")).update(
        end_date=models.F("start_date")
    )


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("leo_backtesting", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="backtestrun",
            name="attempt_count",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="backtestrun",
            name="completed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="backtestrun",
            name="data_checksum",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="backtestrun",
            name="data_points",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="backtestrun",
            name="engine_version",
            field=models.CharField(default="sma-cross-v2", max_length=50),
        ),
        migrations.AddField(
            model_name="backtestrun",
            name="failure_message",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="backtestrun",
            name="requested_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="backtest_runs",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="backtestrun",
            name="spread",
            field=models.DecimalField(
                decimal_places=8,
                default=Decimal("0"),
                max_digits=10,
                validators=[
                    django.core.validators.MinValueValidator(Decimal("0")),
                    django.core.validators.MaxValueValidator(Decimal("0.05")),
                ],
            ),
        ),
        migrations.AddField(
            model_name="backtestrun",
            name="started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="backtestrun",
            name="worker_task_id",
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
        migrations.AlterField(
            model_name="backtestrun",
            name="commission",
            field=models.DecimalField(
                decimal_places=8,
                default=Decimal("0.001"),
                max_digits=10,
                validators=[
                    django.core.validators.MinValueValidator(Decimal("0")),
                    django.core.validators.MaxValueValidator(Decimal("0.10")),
                ],
            ),
        ),
        migrations.AlterField(
            model_name="backtestrun",
            name="initial_cash",
            field=models.DecimalField(
                decimal_places=8,
                default=Decimal("10000"),
                max_digits=24,
                validators=[django.core.validators.MinValueValidator(Decimal("0.01"))],
            ),
        ),
        migrations.AlterField(
            model_name="backtestrun",
            name="slippage",
            field=models.DecimalField(
                decimal_places=8,
                default=Decimal("0"),
                max_digits=10,
                validators=[
                    django.core.validators.MinValueValidator(Decimal("0")),
                    django.core.validators.MaxValueValidator(Decimal("0.05")),
                ],
            ),
        ),
        migrations.AlterField(
            model_name="backtestrun",
            name="status",
            field=models.CharField(
                choices=[
                    ("PENDING", "Pending"),
                    ("RUNNING", "Running"),
                    ("DONE", "Done"),
                    ("FAILED", "Failed"),
                ],
                db_index=True,
                default="PENDING",
                max_length=20,
            ),
        ),
        migrations.AlterModelOptions(
            name="backtestrun",
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="backtestrun",
            index=models.Index(
                fields=["requested_by", "status", "created_at"],
                name="leo_backtes_request_175caf_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="backtestrun",
            index=models.Index(
                fields=["strategy", "created_at"],
                name="leo_backtes_strateg_6e492f_idx",
            ),
        ),
        migrations.RunPython(normalize_existing_runs, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="backtestrun",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status__in", ["PENDING", "RUNNING"])),
                fields=("requested_by", "strategy"),
                name="leo_bt_one_active_per_user_strategy",
            ),
        ),
        migrations.AddConstraint(
            model_name="backtestrun",
            constraint=models.CheckConstraint(
                check=models.Q(("start_date__lte", models.F("end_date"))),
                name="leo_bt_dates_ordered",
            ),
        ),
        migrations.AddConstraint(
            model_name="backtestrun",
            constraint=models.CheckConstraint(
                check=models.Q(("initial_cash__gt", 0)),
                name="leo_bt_initial_cash_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="backtestrun",
            constraint=models.CheckConstraint(
                check=(
                    models.Q(("commission__gte", 0), ("commission__lte", Decimal("0.10")))
                    & models.Q(("spread__gte", 0), ("spread__lte", Decimal("0.05")))
                    & models.Q(("slippage__gte", 0), ("slippage__lte", Decimal("0.05")))
                ),
                name="leo_bt_cost_rates_valid",
            ),
        ),
    ]
