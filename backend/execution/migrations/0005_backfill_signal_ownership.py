from django.db import migrations


def backfill_signal_ownership(apps, schema_editor):
    Order = apps.get_model("execution", "Order")
    Signal = apps.get_model("strategies", "Signal")

    signal_ids = Order.objects.exclude(signal_id__isnull=True).values_list(
        "signal_id", flat=True
    ).distinct()
    for signal_id in signal_ids.iterator():
        user_ids = list(
            Order.objects.filter(signal_id=signal_id)
            .values_list("user_id", flat=True)
            .distinct()[:2]
        )
        if len(user_ids) == 1:
            Signal.objects.filter(pk=signal_id, user__isnull=True).update(
                user_id=user_ids[0]
            )


class Migration(migrations.Migration):

    dependencies = [
        ("execution", "0004_order_closes_position_positionprotection_and_more"),
        ("strategies", "0003_strategy_signal_ownership"),
    ]

    operations = [
        migrations.RunPython(backfill_signal_ownership, migrations.RunPython.noop),
    ]
