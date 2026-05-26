# Auto-générée par makemigrations APRÈS la régression. Linéarisée pour
# dépendre de 0004_recreate_broker_external_ref (qui recrée la table en DB).
# Sans ça, Django voit deux "leaf migrations" 0004 et exige un merge.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('brokers', '0004_recreate_broker_external_ref'),
    ]

    operations = [
        migrations.RenameIndex(
            model_name='brokerexternalref',
            new_name='brokers_bro_interna_645860_idx',
            old_name='brokers_bro_interna_b50d8f_idx',
        ),
        migrations.RenameIndex(
            model_name='brokerexternalref',
            new_name='brokers_bro_broker__b28739_idx',
            old_name='brokers_bro_broker__c20e6f_idx',
        ),
        migrations.AlterField(
            model_name='brokerexternalref',
            name='id',
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID'),
        ),
    ]
