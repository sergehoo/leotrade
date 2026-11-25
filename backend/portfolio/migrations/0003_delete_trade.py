# NEUTRALISÉE — cette migration avait été auto-générée par makemigrations
# parce que Trade (défini dans portfolio/models_trade.py) n'était pas chargé
# par portfolio/models.py. Conserver ce fichier vide permet de garder la
# numérotation cohérente sans détruire la table créée en 0002_add_trade.
#
# La cause racine est corrigée dans portfolio/models.py qui importe
# désormais explicitement Trade. Voir SCAN_ANOMALIES.md §⚠️.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('portfolio', '0002_add_trade'),
    ]

    operations = [
        # Noop : ne supprime PAS Trade. Voir commentaire ci-dessus.
    ]
