# NEUTRALISÉE — auto-générée parce que BrokerExternalRef n'était pas chargé
# par brokers/models.py (le modèle vit dans brokers/models_external_ref.py).
# La cause racine est corrigée par l'import explicite à la fin de
# brokers/models.py. Ce fichier reste pour préserver la numérotation.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('brokers', '0002_broker_external_ref'),
    ]

    operations = [
        # Noop : ne supprime PAS BrokerExternalRef.
    ]
