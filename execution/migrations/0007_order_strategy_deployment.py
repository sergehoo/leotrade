from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("execution", "0006_scope_idempotency_keys"),
        ("strategies", "0004_strategy_deployments"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="strategy_deployment",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="orders",
                to="strategies.strategydeployment",
            ),
        ),
    ]
