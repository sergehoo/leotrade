from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wallet", "0005_alter_payoutdestination_options"),
    ]

    operations = [
        migrations.AlterField(
            model_name="wallettransaction",
            name="provider",
            field=models.CharField(
                blank=True,
                choices=[
                    ("PAYSTACK", "Paystack"),
                    ("STRIPE", "Stripe"),
                    ("ADYEN", "Adyen"),
                    ("MANUAL", "Manual"),
                ],
                max_length=20,
                null=True,
            ),
        ),
    ]
