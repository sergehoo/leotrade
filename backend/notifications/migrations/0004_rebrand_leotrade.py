"""Rebranding Lyneci → LeoTrade dans les gabarits de notification.

Les gabarits vivent en base, pas dans le code : un renommage du dépôt ne
les atteint pas. Sans cette migration, les utilisateurs continueraient à
recevoir des notifications signées « Lyneci » après le déploiement.

Même forme que `0003_rebrand_lyneci`, qui avait opéré le renommage
précédent dans l'autre sens.
"""

from django.db import migrations

OLD = "Lyneci"
NEW = "LeoTrade"


def _rewrite(apps, _schema_editor, old: str, new: str) -> None:
    NotificationTemplate = apps.get_model("notifications", "NotificationTemplate")

    # Toutes les langues : le nom de la marque n'est pas traduit, et
    # restreindre au français laisserait les autres gabarits incohérents.
    for template in NotificationTemplate.objects.all():
        changed_fields = []
        for field in ("body", "subject"):
            current = getattr(template, field, None)
            if not current:
                continue
            updated = current.replace(old, new)
            if updated != current:
                setattr(template, field, updated)
                changed_fields.append(field)
        if changed_fields:
            template.save(update_fields=changed_fields)


def forwards(apps, schema_editor):
    _rewrite(apps, schema_editor, OLD, NEW)


def backwards(apps, schema_editor):
    """Réversible : un rollback de déploiement ne doit pas laisser les
    gabarits sous une marque que le reste de l'application n'utilise plus."""
    _rewrite(apps, schema_editor, NEW, OLD)


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0003_rebrand_lyneci"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
