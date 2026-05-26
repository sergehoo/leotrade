from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from strategies.models import Strategy, StrategyVersion, Signal


@receiver(post_save, sender=Strategy)
def create_initial_strategy_version(sender, instance, created, **kwargs):
    if created and not instance.versions.exists():
        StrategyVersion.objects.create(
            strategy=instance,
            version="1.0.0",
            is_live=True if instance.status in ["PAPER", "LIVE"] else False,
            model_path=instance.model_path,
            parameters=instance.parameters,
            entry_rules=instance.entry_rules,
            exit_rules=instance.exit_rules,
            notes="Version initiale générée automatiquement.",
        )


@receiver(pre_save, sender=StrategyVersion)
def ensure_single_live_version(sender, instance, **kwargs):
    if instance.is_live and instance.strategy_id:
        StrategyVersion.objects.filter(
            strategy_id=instance.strategy_id,
            is_live=True
        ).exclude(pk=instance.pk).update(is_live=False)


@receiver(post_save, sender=Signal)
def update_strategy_last_signal(sender, instance, created, **kwargs):
    if created and instance.strategy_id:
        Strategy.objects.filter(pk=instance.strategy_id).update(last_signal_at=timezone.now())