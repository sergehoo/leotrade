"""
accounting/services.py
======================

TransferService : opération double-entrée atomique Wallet ↔ Portfolio.

Règle d'invariant absolue :
    Sum(Wallet.balance_changes) + Sum(Portfolio.cash_changes) == 0
                                  pour un même Transfer.

Idempotence : request_id unique. Si appelé deux fois avec le même
request_id, retourne l'objet déjà créé sans muter quoi que ce soit.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from .models import Transfer
from portfolio.models import Portfolio
from portfolio.services import PortfolioAccountingService, PortfolioService
from wallet.models import Wallet
from wallet.services_v2 import WalletLedgerService, InsufficientFundsError


log = logging.getLogger("lyneci.accounting.transfer")

MONEY = Decimal("0.01")


def _q(value, default="0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


class TransferError(Exception):
    """Une opération de transfert a échoué."""


class TransferService:
    @staticmethod
    def transfer_wallet_to_portfolio(
        *,
        wallet_id: int,
        portfolio_id: int,
        amount,
        request_id: str,
        description: str = "Transfert vers compte de trading",
        metadata: dict | None = None,
    ) -> Transfer:
        """
        Débite le wallet, crédite le portfolio. Atomique. Idempotent.
        """
        amount = _q(amount)
        if amount <= 0:
            raise ValueError("amount doit être strictement positif")
        if not request_id:
            raise ValueError("request_id obligatoire (idempotency key)")

        # Idempotence : on retourne directement si déjà fait
        existing = Transfer.objects.filter(request_id=request_id).first()
        if existing:
            return existing

        wallet = Wallet.objects.select_related("user").get(pk=wallet_id)
        portfolio = Portfolio.objects.select_related("user").get(pk=portfolio_id)

        if wallet.user_id != portfolio.user_id:
            raise TransferError("Wallet et Portfolio appartiennent à des utilisateurs différents.")
        if not wallet.is_active:
            raise TransferError("Wallet inactif.")
        if not portfolio.is_active:
            raise TransferError("Portfolio inactif.")

        # 1. Crée le record Transfer en PENDING (verrou logique avant de muter)
        transfer = Transfer.objects.create(
            request_id=request_id,
            user_id=wallet.user_id,
            wallet=wallet,
            portfolio=portfolio,
            direction="WALLET_TO_PORTFOLIO",
            amount=amount,
            currency=wallet.currency,
            status="PENDING",
            metadata=metadata or {},
        )

        try:
            # Bloc atomique interne : si une étape échoue, débit/crédit sont
            # annulés ensemble, mais le record Transfer (PENDING → FAILED)
            # survit pour garder une trace de l'échec.
            with transaction.atomic():
                # 2. Débit du Wallet (lève InsufficientFundsError si solde insuffisant)
                wallet_entry = WalletLedgerService.debit(
                    wallet_id=wallet_id,
                    amount=amount,
                    external_event_id=f"transfer:{request_id}:wallet_debit",
                    description=description,
                    metadata={"transfer_id": transfer.id, "portfolio_id": portfolio_id},
                )

                # 3. Crédit du Portfolio
                portfolio_entry = PortfolioAccountingService.add_ledger_entry(
                    portfolio=portfolio,
                    entry_type="DEPOSIT",
                    amount=amount,
                    currency=portfolio.base_currency,
                    reference_type="WALLET_TRANSFER",
                    reference_id=str(transfer.id),
                    description=description,
                    metadata={"transfer_id": transfer.id, "wallet_id": wallet_id, "request_id": request_id},
                )

                # 4. Mise à jour des soldes calculés (recompute_cash_state)
                PortfolioService.recompute_cash_state(portfolio)

                # 5. Marque le transfer comme COMPLETED
                transfer.wallet_ledger_entry = wallet_entry
                transfer.portfolio_ledger_entry = portfolio_entry
                transfer.status = "COMPLETED"
                transfer.completed_at = timezone.now()
                transfer.save(update_fields=[
                    "wallet_ledger_entry", "portfolio_ledger_entry", "status", "completed_at",
                ])

            log.info(
                "transfer.wallet_to_portfolio.ok request_id=%s wallet_id=%s portfolio_id=%s amount=%s",
                request_id, wallet_id, portfolio_id, amount,
            )
            return transfer

        except InsufficientFundsError as exc:
            transfer.status = "FAILED"
            transfer.error_message = f"insufficient_funds: {exc}"
            transfer.save(update_fields=["status", "error_message"])
            raise TransferError(f"Solde wallet insuffisant : {exc}") from exc

        except Exception as exc:
            transfer.status = "FAILED"
            transfer.error_message = f"unexpected: {exc}"
            transfer.save(update_fields=["status", "error_message"])
            log.exception(
                "transfer.wallet_to_portfolio.failed request_id=%s err=%s",
                request_id, exc,
            )
            raise

    @staticmethod
    def transfer_portfolio_to_wallet(
        *,
        wallet_id: int,
        portfolio_id: int,
        amount,
        request_id: str,
        description: str = "Rapatriement vers wallet",
        metadata: dict | None = None,
    ) -> Transfer:
        """
        Inverse : débite le portfolio (en cash disponible) et crédite le wallet.
        """
        amount = _q(amount)
        if amount <= 0:
            raise ValueError("amount doit être strictement positif")
        if not request_id:
            raise ValueError("request_id obligatoire")

        existing = Transfer.objects.filter(request_id=request_id).first()
        if existing:
            return existing

        wallet = Wallet.objects.get(pk=wallet_id)
        portfolio = Portfolio.objects.get(pk=portfolio_id)

        if wallet.user_id != portfolio.user_id:
            raise TransferError("Wallet et Portfolio doivent appartenir au même utilisateur.")

        # Refresh portfolio cash state pour avoir available_cash à jour
        portfolio = PortfolioService.recompute_cash_state(portfolio)
        if portfolio.available_cash < amount:
            raise TransferError(
                f"Cash portfolio insuffisant : available={portfolio.available_cash} requested={amount}"
            )

        transfer = Transfer.objects.create(
            request_id=request_id,
            user_id=wallet.user_id,
            wallet=wallet,
            portfolio=portfolio,
            direction="PORTFOLIO_TO_WALLET",
            amount=amount,
            currency=wallet.currency,
            status="PENDING",
            metadata=metadata or {},
        )

        try:
            # Bloc atomique interne : voir transfer_wallet_to_portfolio.
            with transaction.atomic():
                portfolio_entry = PortfolioAccountingService.add_ledger_entry(
                    portfolio=portfolio,
                    entry_type="WITHDRAWAL",
                    amount=-amount,
                    reference_type="WALLET_TRANSFER",
                    reference_id=str(transfer.id),
                    description=description,
                    metadata={"transfer_id": transfer.id, "wallet_id": wallet_id, "request_id": request_id},
                )
                wallet_entry = WalletLedgerService.credit(
                    wallet_id=wallet_id,
                    amount=amount,
                    external_event_id=f"transfer:{request_id}:wallet_credit",
                    description=description,
                    metadata={"transfer_id": transfer.id, "portfolio_id": portfolio_id},
                )

                PortfolioService.recompute_cash_state(portfolio)

                transfer.wallet_ledger_entry = wallet_entry
                transfer.portfolio_ledger_entry = portfolio_entry
                transfer.status = "COMPLETED"
                transfer.completed_at = timezone.now()
                transfer.save(update_fields=[
                    "wallet_ledger_entry", "portfolio_ledger_entry", "status", "completed_at",
                ])

            log.info(
                "transfer.portfolio_to_wallet.ok request_id=%s amount=%s",
                request_id, amount,
            )
            return transfer

        except Exception as exc:
            transfer.status = "FAILED"
            transfer.error_message = str(exc)
            transfer.save(update_fields=["status", "error_message"])
            raise
