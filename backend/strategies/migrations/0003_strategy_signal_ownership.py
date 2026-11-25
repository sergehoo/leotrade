from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


def backfill_signal_users_from_payload(apps, schema_editor):
    Signal = apps.get_model("strategies", "Signal")
    app_label, model_name = settings.AUTH_USER_MODEL.split(".")
    User = apps.get_model(app_label, model_name)

    valid_user_ids = set(User.objects.values_list("id", flat=True))
    for signal in Signal.objects.filter(user__isnull=True).only("id", "model_output").iterator():
        payload = signal.model_output if isinstance(signal.model_output, dict) else {}
        try:
            user_id = int(payload.get("user_id"))
        except (TypeError, ValueError):
            continue
        if user_id in valid_user_ids:
            Signal.objects.filter(pk=signal.pk, user__isnull=True).update(user_id=user_id)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("strategies", "0002_strategyprediction_actual_label_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="strategy",
            name="name",
            field=models.CharField(max_length=150),
        ),
        migrations.AlterField(
            model_name="strategy",
            name="slug",
            field=models.SlugField(blank=True),
        ),
        migrations.AddField(
            model_name="strategy",
            name="owner",
            field=models.ForeignKey(
                blank=True,
                help_text="Vide pour une stratégie système partagée en lecture seule.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="strategies",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="signal",
            name="user",
            field=models.ForeignKey(
                blank=True,
                help_text="Destinataire du signal. Vide uniquement pour un signal système.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="strategy_signals",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="signal",
            name="reviewed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="signal",
            name="reviewed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="reviewed_strategy_signals",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(
            backfill_signal_users_from_payload,
            migrations.RunPython.noop,
        ),
        migrations.AddIndex(
            model_name="strategy",
            index=models.Index(fields=["owner", "status"], name="strategy_owner_status_idx"),
        ),
        migrations.AddIndex(
            model_name="signal",
            index=models.Index(fields=["user", "status"], name="signal_user_status_idx"),
        ),
        migrations.AddConstraint(
            model_name="strategy",
            constraint=models.UniqueConstraint(
                fields=("owner", "name"),
                name="strategy_unique_owner_name",
            ),
        ),
        migrations.AddConstraint(
            model_name="strategy",
            constraint=models.UniqueConstraint(
                condition=Q(owner__isnull=True),
                fields=("name",),
                name="strategy_unique_system_name",
            ),
        ),
        migrations.AddConstraint(
            model_name="strategy",
            constraint=models.UniqueConstraint(
                fields=("owner", "slug"),
                name="strategy_unique_owner_slug",
            ),
        ),
        migrations.AddConstraint(
            model_name="strategy",
            constraint=models.UniqueConstraint(
                condition=Q(owner__isnull=True),
                fields=("slug",),
                name="strategy_unique_system_slug",
            ),
        ),
    ]
