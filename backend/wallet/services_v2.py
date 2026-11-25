"""
wallet/services_v2.py
=====================

Nouvelle couche WalletLedgerService avec :
  - select_for_update() systématique sur Wallet pour éliminer les races ;
  - création obligatoire d'une WalletLedgerEntry à chaque mutation ;
  - idempotence forte via external_event_id (UNIQUE).

Ce service COEXISTE avec wallet.services.WalletService legacy. Le legacy
est progressivement remplacé via le PATCH_PHASE2_WALLET.md.

Règle d'or : aucune ligne de code, en dehors de ce module et de
accounting.services.TransferService, ne doit modifier directement
wallet.available_balance ou wallet.locked_balance.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import transaction
from django.db.models import F

from .models import Wallet, WalletLedgerEntry, WalletTransaction


log = logging.getLogger("lyneci.wallet.ledger")

MONEY = Decimal("0.01")


def _q(value, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


class InsufficientFundsError(Exception):
    """Solde insuffisant pour l'opération."""


class WalletLedgerService:
    """
    Toute mutation de balance Wallet passe par cette classe.
    """

    # Mapping interne entry_type → effet sur balances
    DEBIT_ON_AVAILABLE = {"DEBIT", "FEE", "REFUND"}  # mvts qui sortent de available
    CREDIT_ON_AVAILABLE = {"CREDIT", "REFUND"}        # CREDIT sort en + ; REFUND prend selon sens
    LOCK_FROM_AVAILABLE = {"LOCK"}                    # available → locked
    UNLOCK_TO_AVAILABLE = {"UNLOCK"}                  # locked → available

    @staticmethod
    @transaction.atomic
    def credit(
        *,
        wallet_id: int,
        amount,
        external_event_id: str,
        transaction_obj: WalletTransaction | None = None,
        description: str = "",
        metadata: dict | None = None,
    ) -> WalletLedgerEntry:
        """
        Crédite le wallet (DEPOSIT, REFUND, ADJUSTMENT positif…).
        Idempotent par external_event_id.
        """
        amount = _q(amount)
        if amount <= 0:
            raise ValueError("amount doit être strictement positif pour credit().")

        existing = _resolve_existing_entry(external_event_id)
        if existing:
            return existing

        wallet = Wallet.objects.select_for_update().get(pk=wallet_id)
        balance_before = (wallet.available_balance or Decimal("0")) + (wallet.locked_balance or Decimal("0"))

        Wallet.objects.filter(pk=wallet.pk).update(
            available_balance=F("available_balance") + amount,
            total_deposited=F("total_deposited") + amount,
        )
        wallet.refresh_from_db(fields=["available_balance", "locked_balance", "total_deposited"])

        entry = WalletLedgerEntry.objects.create(
            wallet=wallet,
            transaction=transaction_obj,
            entry_type="CREDIT",
            amount=amount,
            balance_before=balance_before,
            balance_after=wallet.available_balance + wallet.locked_balance,
            currency=wallet.currency,
            description=description or "Crédit wallet",
            metadata={**(metadata or {}), "external_event_id": external_event_id},
        )
        log.info(
            "wallet.ledger.credit wallet_id=%s amount=%s event=%s entry_id=%s",
            wallet_id, amount, external_event_id, entry.id,
        )
        return entry

    @staticmethod
    @transaction.atomic
    def debit(
        *,
        wallet_id: int,
        amount,
        external_event_id: str,
        transaction_obj: WalletTransaction | None = None,
        description: str = "",
        metadata: dict | None = None,
    ) -> WalletLedgerEntry:
        """
        Débit direct (TRANSFER vers un Portfolio, FEE, ADJUSTMENT négatif…).
        Bloque si available_balance < amount.
        Idempotent.
        """
        amount = _q(amount)
        if amount <= 0:
            raise ValueError("amount doit être strictement positif pour debit().")

        existing = _resolve_existing_entry(external_event_id)
        if existing:
            return existing

        wallet = Wallet.objects.select_for_update().get(pk=wallet_id)
        if (wallet.available_balance or Decimal("0")) < amount:
            raise InsufficientFundsError(
                f"available={wallet.available_balance} < requested={amount}"
            )

        balance_before = (wallet.available_balance or Decimal("0")) + (wallet.locked_balance or Decimal("0"))
        Wallet.objects.filter(pk=wallet.pk).update(
            available_balance=F("available_balance") - amount,
        )
        wallet.refresh_from_db(fields=["available_balance", "locked_balance"])

        entry = WalletLedgerEntry.objects.create(
            wallet=wallet,
            transaction=transaction_obj,
            entry_type="DEBIT",
            amount=amount,
            balance_before=balance_before,
            balance_after=wallet.available_balance + wallet.locked_balance,
            currency=wallet.currency,
            description=description or "Débit wallet",
            metadata={**(metadata or {}), "external_event_id": external_event_id},
        )
        log.info(
            "wallet.ledger.debit wallet_id=%s amount=%s event=%s entry_id=%s",
            wallet_id, amount, external_event_id, entry.id,
        )
        return entry

    @staticmethod
    @transaction.atomic
    def lock(
        *,
        wallet_id: int,
        amount,
        external_event_id: str,
        transaction_obj: WalletTransaction | None = None,
        description: str = "Lock pour retrait",
        metadata: dict | None = None,
    ) -> WalletLedgerEntry:
        """
        Verrouille des fonds (préparation retrait). available → locked.
        Idempotent.
        """
        amount = _q(amount)
        if amount <= 0:
            raise ValueError("amount doit être strictement positif pour lock().")

        existing = _resolve_existing_entry(external_event_id)
        if existing:
            return existing

        wallet = Wallet.objects.select_for_update().get(pk=wallet_id)
        if (wallet.available_balance or Decimal("0")) < amount:
            raise InsufficientFundsError(
                f"available={wallet.available_balance} < requested lock={amount}"
            )

        balance_before = (wallet.available_balance or Decimal("0")) + (wallet.locked_balance or Decimal("0"))
        Wallet.objects.filter(pk=wallet.pk).update(
            available_balance=F("available_balance") - amount,
            locked_balance=F("locked_balance") + amount,
        )
        wallet.refresh_from_db(fields=["available_balance", "locked_balance"])

        entry = WalletLedgerEntry.objects.create(
            wallet=wallet,
            transaction=transaction_obj,
            entry_type="LOCK",
            amount=amount,
            balance_before=balance_before,
            balance_after=wallet.available_balance + wallet.locked_balance,
            currency=wallet.currency,
            description=description,
            metadata={**(metadata or {}), "external_event_id": external_event_id},
        )
        log.info(
            "wallet.ledger.lock wallet_id=%s amount=%s event=%s",
            wallet_id, amount, external_event_id,
        )
        return entry

    @staticmethod
    @transaction.atomic
    def unlock(
        *,
        wallet_id: int,
        amount,
        external_event_id: str,
        transaction_obj: WalletTransaction | None = None,
        to_available: bool = True,
        description: str = "",
        metadata: dict | None = None,
    ) -> WalletLedgerEntry:
        """
        Restitue des fonds verrouillés.
          - to_available=True  → locked → available (rejet de retrait)
          - to_available=False → locked sort définitivement (paiement effectué)
        Idempotent.
        """
        amount = _q(amount)
        if amount <= 0:
            raise ValueError("amount doit être strictement positif pour unlock().")

        existing = _resolve_existing_entry(external_event_id)
        if existing:
            return existing

        wallet = Wallet.objects.select_for_update().get(pk=wallet_id)
        if (wallet.locked_balance or Decimal("0")) < amount:
            raise InsufficientFundsError(
                f"locked={wallet.locked_balance} < requested unlock={amount}"
            )

        balance_before = (wallet.available_balance or Decimal("0")) + (wallet.locked_balance or Decimal("0"))
        update_kwargs = {"locked_balance": F("locked_balance") - amount}
        if to_available:
            update_kwargs["available_balance"] = F("available_balance") + amount
        else:
            update_kwargs["total_withdrawn"] = F("total_withdrawn") + amount

        Wallet.objects.filter(pk=wallet.pk).update(**update_kwargs)
        wallet.refresh_from_db(fields=["available_balance", "locked_balance", "total_withdrawn"])

        entry = WalletLedgerEntry.objects.create(
            wallet=wallet,
            transaction=transaction_obj,
            entry_type="UNLOCK",
            amount=amount if to_available else -amount,  # signe = sens
            balance_before=balance_before,
            balance_after=wallet.available_balance + wallet.locked_balance,
            currency=wallet.currency,
            description=description or ("Unlock vers available" if to_available else "Paiement effectué"),
            metadata={
                **(metadata or {}),
                "external_event_id": external_event_id,
                "to_available": to_available,
            },
        )
        log.info(
            "wallet.ledger.unlock wallet_id=%s amount=%s to_available=%s",
            wallet_id, amount, to_available,
        )
        return entry

    @staticmethod
    def reconstruct_balance_from_ledger(wallet_id: int) -> dict[str, Decimal]:
        """
        Replay du ledger : reconstruit available + locked à partir des entries.
        Pour test et audit.
        """
        entries = WalletLedgerEntry.objects.filter(wallet_id=wallet_id).order_by("created_at", "id")
        avail = Decimal("0")
        locked = Decimal("0")
        for e in entries:
            if e.entry_type == "CREDIT":
                avail += e.amount
            elif e.entry_type in ("DEBIT", "FEE"):
                avail -= e.amount
            elif e.entry_type == "LOCK":
                avail -= e.amount
                locked += e.amount
            elif e.entry_type == "UNLOCK":
                # signe positif = retour vers available ; négatif = sortie définitive
                if e.amount > 0:
                    avail += e.amount
                    locked -= e.amount
                else:
                    locked += e.amount
            elif e.entry_type == "REFUND":
                avail += e.amount
        return {"available": avail.quantize(MONEY), "locked": locked.quantize(MONEY)}


def _resolve_existing_entry(external_event_id: str) -> WalletLedgerEntry | None:
    if not external_event_id:
        return None
    return (
        WalletLedgerEntry.objects
        .filter(metadata__external_event_id=external_event_id)
        .order_by("created_at")
        .first()
    )
