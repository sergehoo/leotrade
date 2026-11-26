"""Efface les états de connexion affirmés sans preuve.

`BrokerAccountTestConnectionView` simulait le test : elle posait
`last_connection_status=True` et `status="ACTIVE"` dès que le broker était
reconnu, sans jamais contacter personne. Des comptes dépourvus
d'identifiants portent donc en base l'affirmation « connexion établie ».

Corriger la vue empêche d'en produire de nouvelles, mais pas d'effacer
celles déjà écrites : l'interface continuerait à afficher
« Identifiants incomplets » et « Connexion établie » côte à côte.

On ne remet à zéro que les comptes dont un secret REQUIS manque — pour
ceux-là, l'affirmation est démontrablement fausse. Un compte pourvu de
ses identifiants garde son état : il a pu être testé réellement.
"""

from django.db import migrations

# Mapping figé dans la migration : une migration doit rester lisible même
# si `REQUIRED_SECRETS` évolue plus tard dans le code.
REQUIRED_SECRETS = {
    "BINANCE": ("API_KEY", "API_SECRET"),
    "MT5": ("PASSWORD",),
    "DERIV": ("DERIV_TOKEN",),
}


def clear_unproven_connection_status(apps, schema_editor):
    BrokerAccount = apps.get_model("brokers", "BrokerAccount")
    BrokerCredential = apps.get_model("brokers", "BrokerCredential")

    for account in BrokerAccount.objects.filter(last_connection_status=True):
        required = REQUIRED_SECRETS.get((account.broker or "").upper(), ())
        if not required:
            continue
        configured = set(
            BrokerCredential.objects
            .filter(broker_account=account, is_active=True)
            .values_list("secret_type", flat=True)
        )
        if all(secret in configured for secret in required):
            continue

        account.last_connection_status = False
        account.last_connection_error = (
            "État réinitialisé : la connexion n'avait jamais été réellement "
            "testée. Renseigne les identifiants puis relance le test."
        )
        if account.status == "ACTIVE":
            account.status = "DRAFT"
        account.save(update_fields=[
            "last_connection_status", "last_connection_error", "status", "updated_at",
        ])


class Migration(migrations.Migration):
    dependencies = [
        ("brokers", "0004_rename_brokers_bro_interna_b50d8f_idx_brokers_bro_interna_645860_idx_and_more"),
    ]

    operations = [
        # Irréversible à dessein : restaurer une affirmation fausse n'a
        # pas de sens, et l'état correct se reconstruit par un vrai test.
        migrations.RunPython(
            clear_unproven_connection_status, migrations.RunPython.noop,
        ),
    ]
