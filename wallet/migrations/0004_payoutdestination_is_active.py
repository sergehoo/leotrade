"""
wallet/migrations/0004_payoutdestination_is_active.py
======================================================

Ajoute le champ is_active sur PayoutDestination.
Ce champ est référencé dans wallet/views.py pour filtrer les destinations
actives lors du retrait. Sans cette migration, le filtre .filter(is_active=True)
échoue en production avec un FieldError.

Migration auto-appliquée — backward compatible (default=True).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("wallet", "0003_paymentprovideraccount_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="payoutdestination",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
    ]
