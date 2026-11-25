# Auto-générée par makemigrations APRÈS la régression. Linéarisée pour
# dépendre de 0004_recreate_trade (qui recrée la table en DB).
# Sans ça, Django voit deux "leaf migrations" 0004 et exige un merge.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('portfolio', '0004_recreate_trade'),
    ]

    operations = [
        migrations.RenameIndex(
            model_name='trade',
            new_name='portfolio_t_portfol_afb8f6_idx',
            old_name='portfolio_t_portfol_a3b1c2_idx',
        ),
        migrations.RenameIndex(
            model_name='trade',
            new_name='portfolio_t_portfol_dc5de1_idx',
            old_name='portfolio_t_portfol_e90df3_idx',
        ),
        migrations.RenameIndex(
            model_name='trade',
            new_name='portfolio_t_broker__9b7230_idx',
            old_name='portfolio_t_broker__c4ee21_idx',
        ),
        migrations.AlterField(
            model_name='trade',
            name='id',
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID'),
        ),
    ]
