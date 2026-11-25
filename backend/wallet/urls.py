from django.urls import path
from .views import (
    wallet_dashboard,
    wallet_history,
    wallet_deposit,
    wallet_deposit_success,
    wallet_deposit_cancel,
    wallet_withdraw, wallet_transaction_detail, wallet_withdrawal_detail, admin_withdrawal_mark_paid,
    admin_withdrawal_reject, admin_wallet_detail, payout_destination_set_default,payout_destination_list,payout_destination_update,payout_destination_create,
    payout_destination_delete, admin_wallet_list, admin_withdrawal_queue, admin_withdrawal_detail, admin_withdrawal_approve,
    wallet_transfer_view, transfer_history,
)
from .webhooks import adyen_webhook, paystack_webhook, stripe_webhook

urlpatterns = [
    path("", wallet_dashboard, name="wallet-dashboard"),
    path("history/", wallet_history, name="wallet-history"),
    path("deposit/", wallet_deposit, name="wallet-deposit"),
    path("deposit/success/", wallet_deposit_success, name="wallet-deposit-success"),
    path("deposit/cancel/", wallet_deposit_cancel, name="wallet-deposit-cancel"),
    path("withdraw/", wallet_withdraw, name="wallet-withdraw"),
    path("webhooks/stripe/", stripe_webhook, name="stripe-webhook"),
    path("webhooks/adyen/", adyen_webhook, name="adyen-webhook"),
    path("webhooks/paystack/", paystack_webhook, name="paystack-webhook"),

    path("transactions/<int:pk>/", wallet_transaction_detail, name="wallet-transaction-detail"),
    path("withdrawals/<int:pk>/", wallet_withdrawal_detail, name="wallet-withdrawal-detail"),

    path("destinations/", payout_destination_list, name="payout-destination-list"),
    path("destinations/create/", payout_destination_create, name="payout-destination-create"),
    path("destinations/<int:pk>/edit/", payout_destination_update, name="payout-destination-update"),
    path("destinations/<int:pk>/set-default/", payout_destination_set_default, name="payout-destination-set-default"),
    path("destinations/<int:pk>/delete/", payout_destination_delete, name="payout-destination-delete"),

    path("transfer/", wallet_transfer_view, name="wallet-transfer"),
    path("transfers/history/", transfer_history, name="transfer-history"),

    path("admin/wallets/", admin_wallet_list, name="admin-wallet-list"),
    path("admin/wallets/<int:pk>/", admin_wallet_detail, name="admin-wallet-detail"),
    path("admin/withdrawals/", admin_withdrawal_queue, name="admin-withdrawal-queue"),
    path("admin/withdrawals/<int:pk>/", admin_withdrawal_detail, name="admin-withdrawal-detail"),
    path("admin/withdrawals/<int:pk>/approve/", admin_withdrawal_approve, name="admin-withdrawal-approve"),
    path("admin/withdrawals/<int:pk>/reject/", admin_withdrawal_reject, name="admin-withdrawal-reject"),
    path("admin/withdrawals/<int:pk>/mark-paid/", admin_withdrawal_mark_paid, name="admin-withdrawal-mark-paid"),

]
