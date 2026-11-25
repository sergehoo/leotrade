from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("execution", "0005_backfill_signal_ownership"),
    ]

    operations = [
        migrations.AlterField(
            model_name="idempotencykey",
            name="key",
            field=models.CharField(db_index=True, max_length=120),
        ),
        migrations.AddConstraint(
            model_name="idempotencykey",
            constraint=models.UniqueConstraint(
                fields=("user", "endpoint", "key"),
                name="execution_unique_user_endpoint_idem_key",
            ),
        ),
    ]
