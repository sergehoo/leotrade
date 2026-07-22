from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("brokers", "0004_rename_brokers_bro_interna_b50d8f_idx_brokers_bro_interna_645860_idx_and_more"),
        ("portfolio", "0005_cashledgerentry_trade_execution_type"),
        ("strategies", "0003_strategy_signal_ownership"),
    ]

    operations = [
        migrations.CreateModel(
            name="StrategyDeployment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "execution_mode",
                    models.CharField(
                        choices=[("PAPER", "Paper"), ("LIVE", "Live")],
                        db_index=True,
                        max_length=10,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("DRAFT", "Draft"),
                            ("ACTIVE", "Active"),
                            ("PAUSED", "Paused"),
                            ("REVOKED", "Revoked"),
                        ],
                        db_index=True,
                        default="DRAFT",
                        max_length=12,
                    ),
                ),
                (
                    "auto_execute",
                    models.BooleanField(
                        default=False,
                        help_text="Autorise l'exécution sans validation manuelle pour ce déploiement.",
                    ),
                ),
                ("activated_at", models.DateTimeField(blank=True, null=True)),
                ("paused_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True)),
                (
                    "activated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="activated_strategy_deployments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "broker_account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="strategy_deployments",
                        to="brokers.brokeraccount",
                    ),
                ),
                (
                    "portfolio",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="strategy_deployments",
                        to="portfolio.portfolio",
                    ),
                ),
                (
                    "strategy",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="deployments",
                        to="strategies.strategy",
                    ),
                ),
                (
                    "strategy_version",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="deployments",
                        to="strategies.strategyversion",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="strategy_deployments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["user", "status"],
                        name="stratdep_user_status_idx",
                    ),
                    models.Index(
                        fields=["strategy", "status"],
                        name="stratdep_strategy_status_idx",
                    ),
                    models.Index(
                        fields=["portfolio", "status"],
                        name="stratdep_portfolio_status_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("strategy", "user", "portfolio"),
                        name="uniq_strat_user_portfolio_dep",
                    ),
                    models.UniqueConstraint(
                        condition=Q(status="ACTIVE"),
                        fields=("strategy", "user"),
                        name="uniq_active_strat_user_dep",
                    ),
                ],
            },
        ),
        migrations.AddField(
            model_name="strategyrun",
            name="deployment",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="runs",
                to="strategies.strategydeployment",
            ),
        ),
    ]
