from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai_assistant", "0004_assistantactionrequest"),
    ]

    operations = [
        migrations.AlterField(
            model_name="assistantmessage",
            name="role",
            field=models.CharField(
                choices=[
                    ("USER", "Utilisateur"),
                    ("ASSISTANT", "Lyneci AI"),
                    ("SYSTEM", "Système"),
                ],
                db_index=True,
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="aiquotapayment",
            name="method",
            field=models.CharField(
                choices=[
                    ("WALLET", "Portefeuille Lyneci"),
                    ("STRIPE", "Stripe (carte / lien)"),
                ],
                max_length=20,
            ),
        ),
    ]
