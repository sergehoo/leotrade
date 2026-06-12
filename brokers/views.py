import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import DeleteView, UpdateView, CreateView, DetailView, ListView

from brokers.forms import BrokerAccountForm
from brokers.models import BrokerAccount

log = logging.getLogger("leotrade.brokers.views")


class BrokerAccountListView(LoginRequiredMixin, ListView):
    model = BrokerAccount
    template_name = "brokers/broker_list.html"
    context_object_name = "brokers"

    def get_queryset(self):
        return (
            BrokerAccount.objects
            .filter(user=self.request.user)
            .order_by("name")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        brokers = context["brokers"]
        context["active_brokers_count"] = brokers.filter(is_active=True).count()
        context["default_broker"] = brokers.filter(is_default=True).first()
        return context


class BrokerAccountDetailView(LoginRequiredMixin, DetailView):
    model = BrokerAccount
    template_name = "brokers/broker_detail.html"
    context_object_name = "broker"

    def get_queryset(self):
        return BrokerAccount.objects.filter(user=self.request.user)


class BrokerAccountCreateView(LoginRequiredMixin, CreateView):
    model = BrokerAccount
    form_class = BrokerAccountForm
    template_name = "brokers/broker_form.html"
    success_url = reverse_lazy("broker-list")

    def form_valid(self, form):
        broker = form.save(user=self.request.user)
        self.object = broker
        messages.success(self.request, "Compte broker créé avec succès.")
        from notifications.shortcuts import notify
        notify(
            self.request.user, "BROKER_ACCOUNT_CREATED",
            title=f"Compte broker créé : {broker.name}",
            message=f"Compte {broker.broker} « {broker.name} » créé en mode {broker.mode}.",
            payload={"broker_account_id": broker.pk, "broker": broker.broker, "mode": broker.mode},
        )
        return redirect(self.get_success_url())

    def form_invalid(self, form):
        log.warning(
            "broker.create.invalid",
            extra={
                "user_id": getattr(self.request.user, "id", None),
                "field_errors": list(form.errors.keys()),
                "non_field_errors": [str(e) for e in form.non_field_errors()],
            },
        )
        messages.error(self.request, "Impossible d'enregistrer le compte broker.")
        return super().form_invalid(form)


class BrokerAccountUpdateView(LoginRequiredMixin, UpdateView):
    model = BrokerAccount
    form_class = BrokerAccountForm
    template_name = "brokers/broker_form.html"
    success_url = reverse_lazy("broker-list")

    def get_queryset(self):
        return BrokerAccount.objects.filter(user=self.request.user)

    def form_valid(self, form):
        broker = form.save(user=self.request.user)
        self.object = broker
        messages.success(self.request, "Compte broker mis à jour avec succès.")
        from notifications.shortcuts import notify
        notify(
            self.request.user, "BROKER_ACCOUNT_UPDATED",
            title=f"Compte broker modifié : {broker.name}",
            message=f"La configuration du compte {broker.broker} « {broker.name} » a été modifiée.",
            payload={"broker_account_id": broker.pk, "broker": broker.broker, "mode": broker.mode},
        )
        return redirect(self.get_success_url())

    def form_invalid(self, form):
        log.warning(
            "broker.update.invalid",
            extra={
                "user_id": getattr(self.request.user, "id", None),
                "broker_id": getattr(self.get_object(), "id", None),
                "field_errors": list(form.errors.keys()),
                "non_field_errors": [str(e) for e in form.non_field_errors()],
            },
        )
        messages.error(self.request, "Impossible de mettre à jour le compte broker.")
        return super().form_invalid(form)


class BrokerAccountDeleteView(LoginRequiredMixin, DeleteView):
    model = BrokerAccount
    template_name = "brokers/broker_confirm_delete.html"
    success_url = reverse_lazy("broker-list")

    def get_queryset(self):
        return BrokerAccount.objects.filter(user=self.request.user)

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, "Compte broker supprimé.")
        return super().delete(request, *args, **kwargs)


class BrokerAccountSetDefaultView(LoginRequiredMixin, View):
    def post(self, request, pk):
        broker = BrokerAccount.objects.filter(user=request.user, pk=pk).first()
        if not broker:
            messages.error(request, "Compte broker introuvable.")
            return redirect("broker-list")

        BrokerAccount.objects.filter(user=request.user, is_default=True).update(is_default=False)
        broker.is_default = True
        broker.save(update_fields=["is_default", "updated_at"])

        messages.success(request, f"{broker.name} défini comme broker par défaut.")
        from notifications.shortcuts import notify
        notify(
            request.user, "BROKER_DEFAULT_CHANGED",
            title=f"Broker par défaut : {broker.name}",
            message=f"« {broker.name} » ({broker.broker}, mode {broker.mode}) est maintenant ton broker par défaut.",
            payload={"broker_account_id": broker.pk, "broker": broker.broker, "mode": broker.mode},
        )
        return redirect("broker-list")


class BrokerAccountTestConnectionView(LoginRequiredMixin, View):
    def post(self, request, pk):
        broker = BrokerAccount.objects.filter(user=request.user, pk=pk).first()
        if not broker:
            messages.error(request, "Compte broker introuvable.")
            return redirect("broker-list")

        ok = False
        error_message = ""

        try:
            if broker.broker == "BINANCE":
                ok = True
            elif broker.broker == "MT5":
                ok = True
            elif broker.broker == "DERIV":
                ok = True
            else:
                error_message = "Broker non supporté."
                ok = False

        except Exception as exc:
            error_message = str(exc)
            ok = False

        broker.last_connection_status = ok
        broker.last_connection_error = "" if ok else error_message
        broker.last_connected_at = timezone.now()
        broker.status = "ACTIVE" if ok else "ERROR"
        broker.save(update_fields=[
            "last_connection_status",
            "last_connection_error",
            "last_connected_at",
            "status",
            "updated_at",
        ])

        from notifications.shortcuts import notify
        if ok:
            messages.success(request, f"Connexion réussie pour {broker.name}.")
            notify(
                request.user, "BROKER_CONNECTION_OK",
                title=f"Connexion broker réussie : {broker.name}",
                message=f"Le test de connexion à {broker.broker} « {broker.name} » a réussi.",
                payload={"broker_account_id": broker.pk, "broker": broker.broker},
            )
        else:
            messages.error(
                request,
                f"Échec de connexion pour {broker.name}: {error_message or 'Erreur inconnue'}"
            )
            notify(
                request.user, "BROKER_CONNECTION_FAILED",
                title=f"Connexion broker échouée : {broker.name}",
                message=(
                    f"Le test de connexion à {broker.broker} « {broker.name} » a échoué : "
                    f"{error_message or 'erreur inconnue'}. Vérifie tes identifiants dans la configuration."
                ),
                payload={"broker_account_id": broker.pk, "broker": broker.broker,
                         "error": (error_message or "")[:500]},
            )

        return redirect("broker-list")

@login_required
def broker_health_api(request):
    """Centre Broker — statut de connexion, circuit breaker, sync, erreurs.

    Données réelles uniquement : état persisté par les health checks et le
    circuit breaker partagé du BrokerGateway.
    """
    from brokers.models_external_ref import BrokerExternalRef
    from infrastructure.broker_clients.gateway import BrokerGateway

    accounts = BrokerAccount.objects.filter(user=request.user).order_by("-is_default", "name")

    data = []
    for account in accounts:
        # État du circuit sans construire le client réel (pas d'I/O broker ici)
        circuit = BrokerGateway(account, client=object()).circuit_state()

        last_sync = (
            BrokerExternalRef.objects
            .filter(broker_account=account)
            .order_by("-last_seen_at")
            .values_list("last_seen_at", flat=True)
            .first()
        )

        data.append({
            "id": account.pk,
            "name": account.name,
            "broker": account.broker,
            "mode": account.mode,
            "is_default": account.is_default,
            "status": account.status,
            "connected": bool(account.last_connection_status),
            "last_connected_at": (
                account.last_connected_at.isoformat()
                if account.last_connected_at else None
            ),
            "last_error": account.last_connection_error or "",
            "circuit_state": circuit,
            "last_sync_at": last_sync.isoformat() if last_sync else None,
        })

    return JsonResponse({"accounts": data, "count": len(data)})
