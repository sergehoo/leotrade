from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, DetailView
from django.shortcuts import get_object_or_404

from trading.models import DerivContract


class DerivContractListView(LoginRequiredMixin, ListView):
    model = DerivContract
    template_name = "trading/deriv_contract_list.html"
    context_object_name = "contracts"
    paginate_by = 30

    def get_queryset(self):
        return (
            DerivContract.objects
            .filter(portfolio__user=self.request.user)
            .select_related("order", "broker_account", "portfolio", "signal")
            .order_by("-created_at")
        )


class DerivContractDetailView(LoginRequiredMixin, DetailView):
    model = DerivContract
    template_name = "trading/deriv_contract_detail.html"
    context_object_name = "contract"

    def get_queryset(self):
        return (
            DerivContract.objects
            .filter(portfolio__user=self.request.user)
            .select_related("order", "broker_account", "portfolio", "signal")
        )