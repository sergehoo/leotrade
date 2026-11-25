from django.shortcuts import render

# Create your views here.
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views.generic import ListView, DetailView, View

from .models import Order
from .services import ExecutionOrchestrator


class OrderListView(LoginRequiredMixin, ListView):
    model = Order
    template_name = "execution/order_list.html"
    context_object_name = "orders"
    paginate_by = 50

    def get_queryset(self):
        return (
            Order.objects
            .filter(user=self.request.user)
            .select_related("portfolio", "broker_account", "asset", "trade_idea", "signal")
            .order_by("-created_at")
        )


class OrderDetailView(LoginRequiredMixin, DetailView):
    model = Order
    template_name = "execution/order_detail.html"
    context_object_name = "order"

    def get_queryset(self):
        return (
            Order.objects
            .filter(user=self.request.user)
            .select_related("portfolio", "broker_account", "asset", "trade_idea", "signal")
            .prefetch_related("fills", "events")
        )


class CancelOrderView(LoginRequiredMixin, View):
    def post(self, request, pk):
        order = Order.objects.filter(user=request.user, pk=pk).first()
        if not order:
            messages.error(request, "Ordre introuvable.")
            return redirect("execution:order_list")

        try:
            ExecutionOrchestrator.cancel_order(order)
            messages.success(request, "Ordre annulé.")
        except Exception as exc:
            messages.error(request, f"Impossible d'annuler l'ordre : {exc}")

        return redirect("execution:order_detail", pk=order.pk)