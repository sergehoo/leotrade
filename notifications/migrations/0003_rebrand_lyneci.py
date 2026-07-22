from django.db import migrations


def rebrand_notification_templates(apps, schema_editor):
    NotificationTemplate = apps.get_model("notifications", "NotificationTemplate")
    for template in NotificationTemplate.objects.filter(language="fr"):
        updated_body = template.body.replace("LeoTrade", "Lyneci")
        updated_subject = template.subject.replace("LeoTrade", "Lyneci")
        changed_fields = []
        if updated_body != template.body:
            template.body = updated_body
            changed_fields.append("body")
        if updated_subject != template.subject:
            template.subject = updated_subject
            changed_fields.append("subject")
        if changed_fields:
            template.save(update_fields=changed_fields)


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0002_seed_templates"),
    ]

    operations = [
        migrations.RunPython(rebrand_notification_templates, migrations.RunPython.noop),
    ]
