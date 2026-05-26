"""
Migration 0005 : ajoute le type "TRADE_EXECUTION" aux choix de CashLedgerEntry.entry_type.

Ce type représente le flux de trésorerie lié à l'ouverture et la clôture de trades
(débit de la mise à l'ouverture, crédit du payout à la clôture).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("portfolio", "0004_rename_portfolio_t_portfol_a3b1c2_idx_portfolio_t_portfol_afb8f6_idx_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="cashledgerentry",
            name="entry_type",
            field=models.CharField(
                choices=[
                    ("DEPOSIT", "Deposit"),
                    ("WITHDRAWAL", "Withdrawal"),
                    ("ORDER_LOCK", "Order Lock"),
                    ("ORDER_RELEASE", "Order Release"),
                    ("FEE", "Fee"),
                    ("PNL_REALIZED", "Realized PnL"),
                    ("TRADE_EXECUTION", "Trade Execution"),
                    ("BROKER_IMPORT", "Broker Import"),
                    ("MANUAL_ADJUSTMENT", "Manual Adjustment"),
                ],
                db_index=True,
                max_length=30,
            ),
        ),
    ]
