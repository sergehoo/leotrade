# wallet/views.py
from decimal import Decimal
from typing import Optional

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .form import DepositForm, WithdrawalForm, PayoutDestinationForm
from .models import (
    Wallet,
    WalletTransaction,
    WithdrawalRequest,
    PaymentMethod,
    ProviderWebhookEvent,
    WalletLedgerEntry,
    PayoutDestination,
)
from .services import WalletService, StripeWalletService, AdyenWalletService, PayoutService


# =========================================================
# Helpers
# =========================================================

def _get_or_create_wallet(request: HttpRequest) -> Wallet:
    wallet, _ = Wallet.objects.get_or_create(
        user=request.user,
        defaults={"currency": "USD"},
    )
    return wallet


def _user_kyc_status(request: HttpRequest) -> Optional[str]:
    profile = getattr(request.user, "kyc_profile", None)
    if not profile:
        return None
    return profile.status


def _can_user_withdraw(request: HttpRequest) -> tuple[bool, str]:
    status = _user_kyc_status(request)
    if status != "APPROVED":
        return False, "Votre dossier KYC doit être approuvé avant tout retrait."
    return True, ""


def _mask_destination(destination: PayoutDestination) -> str:
    if destination.destination_type == "BANK":
        if destination.iban:
            tail = destination.iban[-4:] if len(destination.iban) >= 4 else destination.iban
            return f"{destination.bank_name or 'Bank'} ****{tail}"
        return destination.bank_name or destination.label

    if destination.destination_type == "CARD":
        ref = destination.provider_reference or destination.label
        tail = ref[-4:] if len(ref) >= 4 else ref
        return f"Card ****{tail}"

    if destination.destination_type == "MOBILE_MONEY":
        phone = destination.phone_number or ""
        tail = phone[-4:] if len(phone) >= 4 else phone
        return f"Mobile Money ****{tail}"

    return destination.label


# =========================================================
# User wallet views
# =========================================================

@login_required
def wallet_dashboard(request: HttpRequest) -> HttpResponse:
    wallet = _get_or_create_wallet(request)

    txs = wallet.transactions.all()[:10]
    withdrawals = wallet.withdrawals.all()[:5]
    payout_destinations = request.user.payout_destinations.all()[:5]

    summary = wallet.transactions.aggregate(
        pending_deposit=Sum("amount", filter=Q(tx_type="DEPOSIT", status="PENDING")),
        successful_deposit=Sum("amount", filter=Q(tx_type="DEPOSIT", status="SUCCEEDED")),
        pending_withdrawal=Sum("amount", filter=Q(tx_type="WITHDRAWAL", status__in=["PENDING", "PROCESSING"])),
    )

    from portfolio.models import Portfolio
    from accounting.models import Transfer

    portfolios = list(
        Portfolio.objects
        .filter(user=request.user, is_active=True)
        .order_by("-is_default", "name")
    )
    recent_transfers = list(
        Transfer.objects
        .filter(user=request.user)
        .select_related("portfolio")
        .order_by("-created_at")[:5]
    )

    return render(request, "wallet/dashboard.html", {
        "wallet": wallet,
        "transactions": txs,
        "withdrawals": withdrawals,
        "payout_destinations": payout_destinations,
        "summary": summary,
        "stripe_publishable_key": getattr(settings, "STRIPE_PUBLISHABLE_KEY", ""),
        "kyc_status": _user_kyc_status(request),
        "portfolios": portfolios,
        "recent_transfers": recent_transfers,
    })


@login_required
@require_GET
def wallet_history(request: HttpRequest) -> HttpResponse:
    wallet = _get_or_create_wallet(request)

    tx_type = request.GET.get("type", "").strip()
    status = request.GET.get("status", "").strip()
    q = request.GET.get("q", "").strip()

    transactions = wallet.transactions.all()

    if tx_type:
        transactions = transactions.filter(tx_type=tx_type)

    if status:
        transactions = transactions.filter(status=status)

    if q:
        transactions = transactions.filter(
            Q(provider_reference__icontains=q) |
            Q(description__icontains=q) |
            Q(provider__icontains=q)
        )

    paginator = Paginator(transactions, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "wallet/history.html", {
        "wallet": wallet,
        "transactions": page_obj,
        "page_obj": page_obj,
        "filters": {
            "type": tx_type,
            "status": status,
            "q": q,
        },
    })


@login_required
def wallet_deposit(request: HttpRequest) -> HttpResponse:
    wallet = _get_or_create_wallet(request)

    if request.method == "POST":
        form = DepositForm(request.POST)
        if form.is_valid():
            amount = form.cleaned_data["amount"]
            currency = form.cleaned_data["currency"]
            provider = form.cleaned_data["provider"]

            try:
                if provider == "STRIPE":
                    session, tx = StripeWalletService.create_deposit_checkout_session(
                        user=request.user,
                        wallet=wallet,
                        amount=amount,
                        currency=currency,
                    )
                    return redirect(session.url, code=303)

                elif provider == "ADYEN":
                    adyen_session, tx = AdyenWalletService.create_deposit_session(
                        user=request.user,
                        wallet=wallet,
                        amount=amount,
                        currency=currency,
                    )
                    return render(request, "wallet/deposit.html", {
                        "form": form,
                        "wallet": wallet,
                        "adyen_session": adyen_session,
                        "adyen_client_key_needed": True,
                        "stripe_publishable_key": getattr(settings, "STRIPE_PUBLISHABLE_KEY", ""),
                    })

                else:
                    messages.error(request, "Provider de paiement non pris en charge.")
            except Exception as exc:
                messages.error(request, f"Impossible de démarrer le dépôt : {exc}")
    else:
        form = DepositForm(initial={"currency": wallet.currency})

    return render(request, "wallet/deposit.html", {
        "form": form,
        "wallet": wallet,
        "stripe_publishable_key": getattr(settings, "STRIPE_PUBLISHABLE_KEY", ""),
    })


@login_required
def wallet_deposit_success(request: HttpRequest) -> HttpResponse:
    wallet = _get_or_create_wallet(request)
    messages.success(
        request,
        "Dépôt initié avec succès. Le solde sera crédité après confirmation du provider."
    )
    return render(request, "wallet/deposit_success.html", {"wallet": wallet})


@login_required
def wallet_deposit_cancel(request: HttpRequest) -> HttpResponse:
    wallet = _get_or_create_wallet(request)
    messages.warning(request, "Le dépôt a été annulé.")
    return render(request, "wallet/deposit_cancel.html", {"wallet": wallet})


@login_required
def wallet_withdraw(request: HttpRequest) -> HttpResponse:
    wallet = _get_or_create_wallet(request)
    allowed, reason = _can_user_withdraw(request)

    payout_destinations = request.user.payout_destinations.filter(is_active=True).order_by("-is_default", "-created_at")

    if request.method == "POST":
        # Guard KYC en amont du form pour éviter tout traitement inutile
        if not allowed:
            messages.error(request, reason)
            return redirect("kyc-dashboard")

        form = WithdrawalForm(request.POST, wallet=wallet)

        if form.is_valid():
            destination_id = request.POST.get("payout_destination_id")
            payout_destination = None

            if destination_id:
                payout_destination = get_object_or_404(
                    PayoutDestination,
                    pk=destination_id,
                    user=request.user,
                )

            destination_masked = form.cleaned_data.get("destination_masked") or ""
            if payout_destination:
                destination_masked = _mask_destination(payout_destination)

            try:
                with transaction.atomic():
                    wd, tx = WalletService.lock_funds_for_withdrawal(
                        wallet=wallet,
                        amount=form.cleaned_data["amount"],
                        destination_type=form.cleaned_data["destination_type"],
                        destination_masked=destination_masked,
                    )

                    if payout_destination:
                        wd.metadata = {
                            **wd.metadata,
                            "payout_destination_id": payout_destination.id,
                            "payout_destination_label": payout_destination.label,
                        }
                        wd.save(update_fields=["metadata", "updated_at"])

                    PayoutService.submit_withdrawal(wd)

                messages.success(
                    request,
                    "Demande de retrait créée. Elle sera examinée avant paiement."
                )
                return redirect("wallet-dashboard")

            except Exception as exc:
                messages.error(request, f"Impossible de créer la demande de retrait : {exc}")
    else:
        form = WithdrawalForm(wallet=wallet, initial={"currency": wallet.currency})

    return render(request, "wallet/withdraw.html", {
        "form": form,
        "wallet": wallet,
        "kyc_status": _user_kyc_status(request),
        "can_withdraw": allowed,
        "withdraw_block_reason": reason,
        "payout_destinations": payout_destinations,
    })


@login_required
def wallet_transaction_detail(request: HttpRequest, pk: int) -> HttpResponse:
    wallet = _get_or_create_wallet(request)
    tx = get_object_or_404(
        WalletTransaction.objects.select_related("wallet"),
        pk=pk,
        wallet=wallet,
    )

    ledger_entries = tx.wallet.ledger_entries.filter(transaction=tx).order_by("created_at")
    return render(request, "wallet/transaction_detail.html", {
        "wallet": wallet,
        "transaction": tx,
        "ledger_entries": ledger_entries,
    })


@login_required
def wallet_withdrawal_detail(request: HttpRequest, pk: int) -> HttpResponse:
    wallet = _get_or_create_wallet(request)
    withdrawal = get_object_or_404(
        WithdrawalRequest.objects.select_related("wallet", "payment_method", "reviewed_by"),
        pk=pk,
        wallet=wallet,
    )

    return render(request, "wallet/withdrawal_detail.html", {
        "wallet": wallet,
        "withdrawal": withdrawal,
    })


# =========================================================
# Payout destinations
# =========================================================

@login_required
def payout_destination_list(request: HttpRequest) -> HttpResponse:
    destinations = request.user.payout_destinations.order_by("-is_default", "-created_at")
    return render(request, "wallet/payout_destination_list.html", {
        "destinations": destinations,
    })


@login_required
def payout_destination_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = PayoutDestinationForm(request.POST)
        if form.is_valid():
            destination = form.save(commit=False)
            destination.user = request.user
            destination.save()

            if destination.is_default:
                request.user.payout_destinations.exclude(pk=destination.pk).update(is_default=False)

            messages.success(request, "Destination de retrait ajoutée.")
            return redirect("payout-destination-list")
    else:
        form = PayoutDestinationForm()

    return render(request, "wallet/payout_destination_form.html", {
        "form": form,
        "object": None,
    })


@login_required
def payout_destination_update(request: HttpRequest, pk: int) -> HttpResponse:
    destination = get_object_or_404(PayoutDestination, pk=pk, user=request.user)

    if request.method == "POST":
        form = PayoutDestinationForm(request.POST, instance=destination)
        if form.is_valid():
            destination = form.save()

            if destination.is_default:
                request.user.payout_destinations.exclude(pk=destination.pk).update(is_default=False)

            messages.success(request, "Destination de retrait mise à jour.")
            return redirect("payout-destination-list")
    else:
        form = PayoutDestinationForm(instance=destination)

    return render(request, "wallet/payout_destination_form.html", {
        "form": form,
        "object": destination,
    })


@login_required
@require_POST
def payout_destination_set_default(request: HttpRequest, pk: int) -> HttpResponse:
    destination = get_object_or_404(PayoutDestination, pk=pk, user=request.user)

    request.user.payout_destinations.update(is_default=False)
    destination.is_default = True
    destination.save(update_fields=["is_default"])

    messages.success(request, "Destination par défaut mise à jour.")
    return redirect("payout-destination-list")


@login_required
@require_POST
def payout_destination_delete(request: HttpRequest, pk: int) -> HttpResponse:
    destination = get_object_or_404(PayoutDestination, pk=pk, user=request.user)
    destination.delete()
    messages.success(request, "Destination supprimée.")
    return redirect("payout-destination-list")


# =========================================================
# Wallet ↔ Portfolio transfers
# =========================================================

@login_required
def wallet_transfer_view(request: HttpRequest) -> HttpResponse:
    """
    GET  → affiche le formulaire de transfert
    POST → exécute le transfert (direction dans POST data)
    """
    from portfolio.models import Portfolio
    from accounting.services import TransferService, TransferError
    import uuid

    wallet = _get_or_create_wallet(request)

    portfolios = list(
        Portfolio.objects
        .filter(user=request.user, is_active=True)
        .order_by("-is_default", "name")
    )

    if request.method == "POST":
        direction = request.POST.get("direction", "")  # to_portfolio | to_wallet
        portfolio_id = request.POST.get("portfolio_id", "")
        amount_str = request.POST.get("amount", "").replace(",", ".").strip()

        # --- Validation ---
        try:
            amount = Decimal(amount_str)
            if amount <= 0:
                raise ValueError
        except (ValueError, Exception):
            messages.error(request, "Montant invalide.")
            return render(request, "wallet/transfer.html", {
                "wallet": wallet,
                "portfolios": portfolios,
                "direction": direction,
                "portfolio_id": portfolio_id,
                "amount": amount_str,
            })

        if not portfolio_id:
            messages.error(request, "Sélectionnez un portfolio.")
            return render(request, "wallet/transfer.html", {
                "wallet": wallet,
                "portfolios": portfolios,
                "direction": direction,
            })

        try:
            portfolio = Portfolio.objects.get(
                pk=int(portfolio_id),
                user=request.user,
                is_active=True,
            )
        except (Portfolio.DoesNotExist, ValueError):
            messages.error(request, "Portfolio introuvable.")
            return render(request, "wallet/transfer.html", {
                "wallet": wallet,
                "portfolios": portfolios,
            })

        request_id = f"ui:{request.user.pk}:{direction}:{uuid.uuid4().hex[:16]}"

        try:
            if direction == "to_portfolio":
                TransferService.transfer_wallet_to_portfolio(
                    wallet_id=wallet.pk,
                    portfolio_id=portfolio.pk,
                    amount=amount,
                    request_id=request_id,
                    description=f"Transfert vers portfolio « {portfolio.name} »",
                )
                messages.success(
                    request,
                    f"{amount:.2f} {wallet.currency} transférés vers « {portfolio.name} »."
                )
            elif direction == "to_wallet":
                TransferService.transfer_portfolio_to_wallet(
                    wallet_id=wallet.pk,
                    portfolio_id=portfolio.pk,
                    amount=amount,
                    request_id=request_id,
                    description=f"Rapatriement depuis portfolio « {portfolio.name} »",
                )
                messages.success(
                    request,
                    f"{amount:.2f} {wallet.currency} rapatriés depuis « {portfolio.name} »."
                )
            else:
                messages.error(request, "Direction invalide.")
                return render(request, "wallet/transfer.html", {
                    "wallet": wallet,
                    "portfolios": portfolios,
                })

            return redirect("wallet-dashboard")

        except TransferError as exc:
            messages.error(request, f"Transfert refusé : {exc}")
        except Exception as exc:
            messages.error(request, f"Erreur inattendue : {exc}")

        return render(request, "wallet/transfer.html", {
            "wallet": wallet,
            "portfolios": portfolios,
            "direction": direction,
            "portfolio_id": portfolio_id,
            "amount": amount_str,
        })

    # GET
    return render(request, "wallet/transfer.html", {
        "wallet": wallet,
        "portfolios": portfolios,
        "direction": request.GET.get("direction", ""),
        "portfolio_id": request.GET.get("portfolio_id", ""),
    })


@login_required
def transfer_history(request: HttpRequest) -> HttpResponse:
    """Historique paginé des transferts Wallet ↔ Portfolio."""
    from accounting.models import Transfer

    wallet = _get_or_create_wallet(request)

    transfers_qs = (
        Transfer.objects
        .filter(user=request.user)
        .select_related("portfolio")
        .order_by("-created_at")
    )

    paginator = Paginator(transfers_qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "wallet/transfer_history.html", {
        "wallet": wallet,
        "page_obj": page_obj,
        "transfers": page_obj.object_list,
    })


# =========================================================
# Staff / admin withdrawal review
# =========================================================

@staff_member_required
def admin_withdrawal_queue(request: HttpRequest) -> HttpResponse:
    status = request.GET.get("status", "").strip()

    withdrawals = WithdrawalRequest.objects.select_related(
        "wallet",
        "wallet__user",
        "payment_method",
        "reviewed_by",
    ).order_by("-created_at")

    if status:
        withdrawals = withdrawals.filter(status=status)

    paginator = Paginator(withdrawals, 30)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "wallet/admin/withdrawal_queue.html", {
        "withdrawals": page_obj,
        "page_obj": page_obj,
        "status_filter": status,
    })


@staff_member_required
def admin_withdrawal_detail(request: HttpRequest, pk: int) -> HttpResponse:
    withdrawal = get_object_or_404(
        WithdrawalRequest.objects.select_related(
            "wallet",
            "wallet__user",
            "payment_method",
            "reviewed_by",
        ),
        pk=pk,
    )

    related_transactions = WalletTransaction.objects.filter(
        wallet=withdrawal.wallet,
        tx_type="WITHDRAWAL",
        amount=withdrawal.amount,
    ).order_by("-created_at")

    return render(request, "wallet/admin/withdrawal_detail.html", {
        "withdrawal": withdrawal,
        "related_transactions": related_transactions,
    })


@staff_member_required
@require_POST
def admin_withdrawal_approve(request: HttpRequest, pk: int) -> HttpResponse:
    withdrawal = get_object_or_404(WithdrawalRequest, pk=pk)

    if withdrawal.status not in ["PENDING", "UNDER_REVIEW"]:
        messages.error(request, "Cette demande ne peut plus être approuvée.")
        return redirect("admin-withdrawal-detail", pk=withdrawal.pk)

    withdrawal.status = "APPROVED"
    withdrawal.reviewed_by = request.user
    withdrawal.reviewed_at = timezone.now()
    withdrawal.admin_note = request.POST.get("admin_note", "")
    withdrawal.save(update_fields=["status", "reviewed_by", "reviewed_at", "admin_note", "updated_at"])

    messages.success(request, "Retrait approuvé.")
    return redirect("admin-withdrawal-detail", pk=withdrawal.pk)


@staff_member_required
@require_POST
def admin_withdrawal_reject(request: HttpRequest, pk: int) -> HttpResponse:
    withdrawal = get_object_or_404(WithdrawalRequest, pk=pk)

    if withdrawal.status not in ["PENDING", "UNDER_REVIEW", "APPROVED"]:
        messages.error(request, "Cette demande ne peut pas être rejetée.")
        return redirect("admin-withdrawal-detail", pk=withdrawal.pk)

    reason = request.POST.get("reason", "").strip() or "Retrait rejeté par l'administration."

    try:
        WalletService.reject_withdrawal(withdrawal, reason=reason)
        withdrawal.reviewed_by = request.user
        withdrawal.reviewed_at = timezone.now()
        withdrawal.admin_note = request.POST.get("admin_note", "")
        withdrawal.save(update_fields=["reviewed_by", "reviewed_at", "admin_note", "updated_at"])

        messages.success(request, "Retrait rejeté et fonds débloqués.")
    except Exception as exc:
        messages.error(request, f"Impossible de rejeter la demande : {exc}")

    return redirect("admin-withdrawal-detail", pk=withdrawal.pk)


@staff_member_required
@require_POST
def admin_withdrawal_mark_paid(request: HttpRequest, pk: int) -> HttpResponse:
    withdrawal = get_object_or_404(WithdrawalRequest, pk=pk)

    if withdrawal.status not in ["APPROVED", "UNDER_REVIEW"]:
        messages.error(request, "Cette demande ne peut pas être marquée payée.")
        return redirect("admin-withdrawal-detail", pk=withdrawal.pk)

    provider = request.POST.get("provider") or withdrawal.provider or "MANUAL"
    provider_reference = request.POST.get("provider_reference", "").strip() or None

    try:
        WalletService.mark_withdrawal_paid(
            withdrawal=withdrawal,
            provider=provider,
            provider_reference=provider_reference,
        )

        withdrawal.reviewed_by = request.user
        withdrawal.reviewed_at = timezone.now()
        withdrawal.admin_note = request.POST.get("admin_note", "")
        withdrawal.save(update_fields=["reviewed_by", "reviewed_at", "admin_note", "updated_at"])

        messages.success(request, "Retrait marqué comme payé.")
    except Exception as exc:
        messages.error(request, f"Impossible de marquer la demande comme payée : {exc}")

    return redirect("admin-withdrawal-detail", pk=withdrawal.pk)


# =========================================================
# Staff / admin wallet overview
# =========================================================

@staff_member_required
def admin_wallet_list(request: HttpRequest) -> HttpResponse:
    q = request.GET.get("q", "").strip()

    wallets = Wallet.objects.select_related("user").order_by("-updated_at")

    if q:
        wallets = wallets.filter(
            Q(user__email__icontains=q) |
            Q(user__username__icontains=q)
        )

    paginator = Paginator(wallets, 30)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "wallet/admin/wallet_list.html", {
        "wallets": page_obj,
        "page_obj": page_obj,
        "q": q,
    })


@staff_member_required
def admin_wallet_detail(request: HttpRequest, pk: int) -> HttpResponse:
    wallet = get_object_or_404(Wallet.objects.select_related("user"), pk=pk)

    transactions = wallet.transactions.all()[:20]
    withdrawals = wallet.withdrawals.all()[:10]
    ledger_entries = wallet.ledger_entries.all()[:20]

    return render(request, "wallet/admin/wallet_detail.html", {
        "wallet": wallet,
        "transactions": transactions,
        "withdrawals": withdrawals,
        "ledger_entries": ledger_entries,
    })

# from django.shortcuts import render
#
# # Create your views here.
# from decimal import Decimal
# from django.contrib import messages
# from django.contrib.auth.decorators import login_required
# from django.core.cache import cache
# from django.shortcuts import get_object_or_404, redirect, render
# from django.views.decorators.http import require_GET, require_POST
# from django.conf import settings
#
# from .form import DepositForm, WithdrawalForm
# from .models import Wallet, WalletTransaction, WithdrawalRequest
# from .services import WalletService, StripeWalletService, AdyenWalletService, PayoutService
#
#
# @login_required
# def wallet_dashboard(request):
#     wallet, _ = Wallet.objects.get_or_create(user=request.user)
#     txs = wallet.transactions.all()[:10]
#     withdrawals = wallet.withdrawals.all()[:5]
#     return render(request, "wallet/dashboard.html", {
#         "wallet": wallet,
#         "transactions": txs,
#         "withdrawals": withdrawals,
#         "stripe_publishable_key": settings.STRIPE_PUBLISHABLE_KEY,
#     })
#
#
# @login_required
# @require_GET
# def wallet_history(request):
#     wallet, _ = Wallet.objects.get_or_create(user=request.user)
#     return render(request, "wallet/history.html", {
#         "wallet": wallet,
#         "transactions": wallet.transactions.all(),
#     })
#
#
# @login_required
# def wallet_deposit(request):
#     wallet, _ = Wallet.objects.get_or_create(user=request.user)
#
#     if request.method == "POST":
#         form = DepositForm(request.POST)
#         if form.is_valid():
#             amount = form.cleaned_data["amount"]
#             currency = form.cleaned_data["currency"]
#             provider = form.cleaned_data["provider"]
#
#             try:
#                 if provider == "STRIPE":
#                     session, tx = StripeWalletService.create_deposit_checkout_session(
#                         user=request.user,
#                         wallet=wallet,
#                         amount=amount,
#                         currency=currency,
#                     )
#                     return redirect(session.url, code=303)
#                 else:
#                     adyen_session, tx = AdyenWalletService.create_deposit_session(
#                         user=request.user,
#                         wallet=wallet,
#                         amount=amount,
#                         currency=currency,
#                     )
#                     return render(request, "wallet/deposit.html", {
#                         "form": form,
#                         "wallet": wallet,
#                         "adyen_session": adyen_session,
#                         "adyen_client_key_needed": True,
#                     })
#             except Exception as exc:
#                 messages.error(request, f"Impossible de démarrer le dépôt : {exc}")
#     else:
#         form = DepositForm(initial={"currency": wallet.currency})
#
#     return render(request, "wallet/deposit.html", {
#         "form": form,
#         "wallet": wallet,
#         "stripe_publishable_key": settings.STRIPE_PUBLISHABLE_KEY,
#     })
#
#
# @login_required
# def wallet_deposit_success(request):
#     messages.success(request, "Dépôt initié avec succès. Le solde sera crédité après confirmation du provider.")
#     return render(request, "wallet/deposit_success.html", {"wallet": request.user.wallet})
#
#
# @login_required
# def wallet_deposit_cancel(request):
#     messages.warning(request, "Le dépôt a été annulé.")
#     return render(request, "wallet/deposit_cancel.html", {"wallet": request.user.wallet})
#
#
# @login_required
# def wallet_withdraw(request):
#     wallet, _ = Wallet.objects.get_or_create(user=request.user)
#     if request.method == "POST":
#         form = WithdrawalForm(request.POST, wallet=wallet)
#         if form.is_valid():
#             try:
#                 wd, tx = WalletService.lock_funds_for_withdrawal(
#                     wallet=wallet,
#                     amount=form.cleaned_data["amount"],
#                     destination_type=form.cleaned_data["destination_type"],
#                     destination_masked=form.cleaned_data["destination_masked"],
#                 )
#                 PayoutService.submit_withdrawal(wd)
#                 messages.success(request, "Demande de retrait créée. Elle sera examinée avant paiement.")
#                 return redirect("wallet-dashboard")
#             except Exception as exc:
#                 messages.error(request, f"Impossible de créer la demande de retrait : {exc}")
#     else:
#         form = WithdrawalForm(wallet=wallet, initial={"currency": wallet.currency})
#
#     return render(request, "wallet/withdraw.html", {
#         "form": form,
#         "wallet": wallet,
#     })