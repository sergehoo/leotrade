"""
api/serializers/wallet.py
=========================

Contrat du portefeuille électronique.

Deux principes gouvernent ce contrat :

  - l'argent réel (`Wallet`) et le capital de trading (`Portfolio`) sont
    exposés séparément et nommés distinctement. Les confondre conduit à
    croire qu'on dispose d'une somme qu'on n'a pas ;
  - aucune route ne déclenche de flux financier. Une demande de retrait
    est créée à l'état PENDING et attend une revue ; aucun dépôt ne peut
    être initié depuis cette API.
"""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from wallet.models import WalletLedgerEntry, WalletTransaction, WithdrawalRequest


class WalletSummarySerializer(serializers.Serializer):
    has_wallet = serializers.BooleanField()
    currency = serializers.CharField(allow_null=True)
    is_active = serializers.BooleanField()

    # Montants en chaîne : calculés en Decimal, aucun client n'a
    # d'équivalent natif.
    available_balance = serializers.CharField(allow_null=True)
    locked_balance = serializers.CharField(allow_null=True)
    total_balance = serializers.CharField(allow_null=True)
    total_deposited = serializers.CharField(allow_null=True)
    total_withdrawn = serializers.CharField(allow_null=True)

    #: Capital des portefeuilles dont les ordres n'atteignent aucun marché.
    simulated_trading_capital = serializers.CharField(allow_null=True)
    #: Capital des portefeuilles branchés sur un compte broker réel.
    live_trading_capital = serializers.CharField(allow_null=True)

    pending_withdrawals_count = serializers.IntegerField()
    pending_withdrawals_amount = serializers.CharField(allow_null=True)

    #: Faux quand le solde n'est pas intégralement expliqué par le grand
    #: livre. L'information appartient au propriétaire du solde.
    is_reconciled = serializers.BooleanField()
    unexplained_amount = serializers.CharField(allow_null=True)
    ledger_entry_count = serializers.IntegerField()
    ledger_break_count = serializers.IntegerField()


class WalletLedgerEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = WalletLedgerEntry
        fields = [
            "id", "entry_type", "amount", "currency",
            "balance_before", "balance_after",
            "description", "created_at",
        ]
        read_only_fields = fields


class WalletTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = WalletTransaction
        fields = [
            "id", "tx_type", "status", "amount", "currency",
            "provider", "description", "created_at", "processed_at",
        ]
        read_only_fields = fields


class WithdrawalRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = WithdrawalRequest
        fields = [
            "id", "amount", "fee_amount", "currency",
            "destination_type", "destination_masked",
            "status", "failure_reason",
            "created_at", "reviewed_at",
        ]
        read_only_fields = [
            "id", "fee_amount", "currency", "status", "failure_reason",
            "created_at", "reviewed_at",
        ]


class WithdrawalCreateSerializer(serializers.Serializer):
    """Demande de retrait.

    Crée un enregistrement PENDING ; aucun mouvement de fonds n'est
    déclenché ici. Les bornes reprennent celles du formulaire Django
    (`wallet/form.py`), afin que les deux surfaces refusent les mêmes
    montants — une API plus permissive que le formulaire serait le
    chemin qu'on emprunte pour contourner la limite.
    """

    MIN_AMOUNT = Decimal("5.00")
    MAX_AMOUNT = Decimal("100000.00")

    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    destination_type = serializers.ChoiceField(choices=["BANK", "CARD"], default="BANK")
    destination_masked = serializers.CharField(
        max_length=80, required=False, allow_blank=True,
    )

    def validate_amount(self, value: Decimal) -> Decimal:
        if value < self.MIN_AMOUNT:
            raise serializers.ValidationError(
                f"Le montant minimum est {self.MIN_AMOUNT}."
            )
        if value > self.MAX_AMOUNT:
            raise serializers.ValidationError(
                f"Le montant maximum par opération est {self.MAX_AMOUNT}."
            )
        return value

    def validate_destination_masked(self, value: str) -> str:
        """Un numéro de compte complet ne doit jamais transiter ici.

        Seule une forme masquée est acceptée : le champ sert à aider
        l'utilisateur à reconnaître sa destination, pas à la définir.
        """
        cleaned = (value or "").strip()
        digits = [char for char in cleaned if char.isdigit()]
        if len(digits) > 6:
            raise serializers.ValidationError(
                "N'indique qu'une forme masquée de ta destination "
                "(les derniers chiffres suffisent)."
            )
        return cleaned
