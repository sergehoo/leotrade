from django.db import migrations


def backfill_trading_ownership(apps, schema_editor):
    TradingIntent = apps.get_model("trading", "TradingIntent")
    TradeIdea = apps.get_model("trading", "TradeIdea")
    Strategy = apps.get_model("strategies", "Strategy")
    Signal = apps.get_model("strategies", "Signal")

    generated_strategy_ids = Strategy.objects.filter(
        owner__isnull=True,
        description__startswith="Stratégie générée automatiquement pour l’intention",
    ).values_list("id", flat=True)
    for strategy_id in generated_strategy_ids.iterator():
        user_ids = list(
            TradingIntent.objects.filter(strategy_id=strategy_id)
            .values_list("user_id", flat=True)
            .distinct()[:2]
        )
        if len(user_ids) == 1:
            Strategy.objects.filter(pk=strategy_id, owner__isnull=True).update(
                owner_id=user_ids[0]
            )

    signal_ids = TradeIdea.objects.exclude(signal_id__isnull=True).values_list(
        "signal_id", flat=True
    ).distinct()
    for signal_id in signal_ids.iterator():
        user_ids = list(
            TradeIdea.objects.filter(signal_id=signal_id)
            .values_list("user_id", flat=True)
            .distinct()[:2]
        )
        if len(user_ids) == 1:
            Signal.objects.filter(pk=signal_id, user__isnull=True).update(
                user_id=user_ids[0]
            )


class Migration(migrations.Migration):

    dependencies = [
        ("strategies", "0003_strategy_signal_ownership"),
        ("trading", "0002_alter_tradeidea_user"),
    ]

    operations = [
        migrations.RunPython(backfill_trading_ownership, migrations.RunPython.noop),
    ]
