from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render

# Create your views here.
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import ListView, View, CreateView, DetailView
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages

from portfolio.models import Portfolio
from risk.engine import RiskEngine
from strategies.models import Signal
# from risk.services import RiskEngine
from trading.forms import TradingIntentForm
from trading.market_data import get_all_market_data, get_landing_market_data
from trading.models import TradingIntent
from trading.services.execution.base_execution import IntentExecutionService, IntentMonitoringService
from strategies.services.signal_review import SignalReviewError, SignalReviewService
from strategies.services.deployment import StrategyDeploymentService

# Source de vérité pour les ordres : execution.Order. trading.Order existe encore
# pour compatibilité historique mais n'est plus écrit. Cf. Phase 4.
from execution.models import Order as ExecutionOrder
from execution.services import ExecutionOrchestrator




def market_data_api(request):
    cache_key = "landing_market_data"
    data = cache.get(cache_key)

    if data is None:
        data = get_landing_market_data()
        cache.set(cache_key, data, timeout=30)

    # available=False → le frontend affiche un état "source indisponible"
    return JsonResponse({"data": data, "available": bool(data)})


@login_required
def signal_list_api(request):
    """AJAX endpoint — retourne les signaux en JSON pour le polling Alpine."""
    qs = Signal.objects.visible_to(request.user).select_related(
        "strategy", "strategy__asset", "strategy__timeframe"
    ).order_by("-created_at")

    status = request.GET.get("status")
    side = request.GET.get("side")
    strategy_id = request.GET.get("strategy_id")
    if status:
        qs = qs.filter(status=status)
    if side:
        qs = qs.filter(side=side)
    if strategy_id:
        qs = qs.filter(strategy_id=strategy_id)

    qs = qs[:50]

    data = []
    for s in qs:
        data.append({
            "id": s.id,
            "symbol": s.strategy.asset.symbol if s.strategy and s.strategy.asset else "—",
            "strategy_name": s.strategy.name if s.strategy else "—",
            "side": s.side,
            "confidence": float(s.confidence or 0),
            "price": str(s.price or ""),
            "status": s.status,
            "created_at": s.created_at.strftime("%d/%m %H:%M") if s.created_at else "",
        })

    return JsonResponse({"signals": data, "count": len(data)})

class SignalListView(LoginRequiredMixin, ListView):
    model = Signal
    template_name = "trading/signal_list.html"
    context_object_name = "signals"
    paginate_by = 50

    def get_queryset(self):
        return Signal.objects.visible_to(self.request.user).select_related(
            "strategy", "strategy__asset", "strategy__owner", "user"
        ).order_by("-created_at")

class ExecuteSignalView(LoginRequiredMixin, View):
    def post(self, request, pk):
        signal = get_object_or_404(
            Signal.objects.executable_by(request.user).select_related(
                "strategy", "strategy__asset", "strategy__owner", "user"
            ),
            pk=pk,
        )
        strategy_deployment = None
        if signal.strategy.status == "LIVE":
            strategy_deployment = StrategyDeploymentService.active_for(
                strategy=signal.strategy,
                user=request.user,
            )
            if strategy_deployment is None:
                messages.error(
                    request,
                    "Aucun déploiement Live actif n'est configuré pour cette stratégie.",
                )
                return redirect("trading:signal-list")
            portfolio = strategy_deployment.portfolio
        else:
            portfolio = Portfolio.objects.filter(
                user=request.user,
                is_default=True,
            ).select_related("broker_account").first()

        if not portfolio:
            messages.error(request, "Aucun portefeuille par défaut.")
            return redirect("trading:signal-list")

        risk_decision = RiskEngine(portfolio).evaluate(signal)

        if risk_decision.decision == "REJECT":
            messages.error(request, f"Signal rejeté: {risk_decision.reason}")
            try:
                SignalReviewService.reject(signal_id=signal.id, user=request.user)
            except SignalReviewError:
                pass
            return redirect("trading:signal-list")

        try:
            signal = SignalReviewService.approve(signal_id=signal.id, user=request.user)
            order = ExecutionOrchestrator.create_order(
                user=request.user,
                portfolio=portfolio,
                broker_account=portfolio.broker_account,
                symbol=signal.strategy.asset.symbol,
                side=signal.side,
                approved_quantity=risk_decision.approved_quantity,
                requested_stake_amount=risk_decision.approved_stake,
                approved_notional=risk_decision.approved_notional,
                requested_price=signal.price,
                signal=signal,
                strategy_deployment=strategy_deployment,
                asset=signal.strategy.asset,
                source="AI_ASSISTED",
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                metadata={"source": "signal_user_validation"},
            )
            ExecutionOrchestrator.submit_order(order)
            messages.success(request, "Signal exécuté.")
        except Exception as exc:
            messages.error(request, f"Erreur lors de l'exécution du signal : {exc}")

        return redirect("trading:signal-list")

class OrderListView(LoginRequiredMixin, ListView):
    """
    Liste les VRAIS ordres (execution.Order — source de vérité).
    Avant le fix : interrogeait trading.Order (orpheline) → page vide.
    """
    model = ExecutionOrder
    template_name = "trading/order_list.html"
    context_object_name = "orders"
    paginate_by = 30

    def get_queryset(self):
        qs = ExecutionOrder.objects.filter(
            user=self.request.user
        ).select_related(
            "broker_account", "portfolio", "signal", "trade_idea", "asset"
        ).order_by("-created_at")

        # Filtres optionnels via query string : ?status=FILLED&mode=LIVE
        status = self.request.GET.get("status")
        mode = self.request.GET.get("mode")
        symbol = self.request.GET.get("symbol")
        if status:
            qs = qs.filter(status=status)
        if mode:
            qs = qs.filter(mode=mode)
        if symbol:
            qs = qs.filter(symbol__icontains=symbol)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Stats d'en-tête (sur la même base, full queryset utilisateur)
        full_qs = ExecutionOrder.objects.filter(user=self.request.user)
        ctx["count_total"] = full_qs.count()
        ctx["count_filled"] = full_qs.filter(status="FILLED").count()
        ctx["count_open"] = full_qs.filter(
            status__in=["PENDING_SUBMIT", "SUBMITTED", "PARTIALLY_FILLED"]
        ).count()
        ctx["count_failed"] = full_qs.filter(
            status__in=["REJECTED", "FAILED", "CANCELLED", "EXPIRED"]
        ).count()
        ctx["filters"] = {
            "status": self.request.GET.get("status", ""),
            "mode": self.request.GET.get("mode", ""),
            "symbol": self.request.GET.get("symbol", ""),
        }
        return ctx


class OrderDetailView(LoginRequiredMixin, DetailView):
    """
    Détail d'un ordre execution.Order avec ses fills + événements.
    """
    model = ExecutionOrder
    template_name = "trading/order_detail.html"
    context_object_name = "order"

    def get_queryset(self):
        return ExecutionOrder.objects.filter(
            user=self.request.user
        ).select_related(
            "broker_account", "portfolio", "signal", "trade_idea", "asset"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        order = self.object
        ctx["fills"] = list(order.fills.all().order_by("-fill_time"))
        ctx["events"] = list(order.events.all().order_by("-created_at")[:50])

        # Mapping vers Deriv / Binance / MT5 via BrokerExternalRef.
        # On force l'évaluation (list(...)) pour que toute erreur DB soit
        # capturée ICI plutôt que dans le template (où elle deviendrait fatale).
        # Cas typiques : table absente parce qu'une migration parasite
        # a supprimé le modèle puis a été neutralisée — la table reste à
        # recréer (cf. migration 0004_recreate_broker_external_ref).
        ctx["broker_refs"] = []
        ctx["broker_refs_error"] = ""
        try:
            from brokers.models_external_ref import BrokerExternalRef
            ctx["broker_refs"] = list(
                BrokerExternalRef.objects.filter(
                    internal_kind="ORDER", internal_id=str(order.id)
                )
            )
        except Exception as exc:
            # ProgrammingError (table missing), ImportError, etc. → page reste lisible
            import logging
            logging.getLogger("lyneci.trading.views").warning(
                "order_detail.broker_refs_unavailable order_id=%s err=%s",
                order.id, exc,
            )
            ctx["broker_refs_error"] = str(exc)
        return ctx


class TradingIntentListView(LoginRequiredMixin, ListView):
    model = TradingIntent
    template_name = "trading/intent_list.html"
    context_object_name = "intents"
    paginate_by = 20

    def get_queryset(self):
        return TradingIntent.objects.filter(user=self.request.user).select_related(
            "portfolio", "broker_account", "strategy"
        ).order_by("-created_at")


class TradingIntentDetailView(LoginRequiredMixin, DetailView):
    model = TradingIntent
    template_name = "trading/intent_detail.html"
    context_object_name = "intent"

    def get_queryset(self):
        return TradingIntent.objects.filter(user=self.request.user).select_related(
            "portfolio", "broker_account", "strategy"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        intent = self.object
        # Rafraîchissement des métriques uniquement si l'intention est active
        # pour éviter des effets de bord sur une route GET.
        if intent.status == "RUNNING":
            IntentMonitoringService.refresh_metrics(intent)

        ctx["events"] = intent.events.all().order_by("-created_at")[:50]
        ctx["orders"] = (
            ExecutionOrder.objects
            .filter(
                portfolio=intent.portfolio,
                signal__strategy=intent.strategy,
            )
            .order_by("-created_at")[:20]
            if intent.strategy_id
            else ExecutionOrder.objects.none()
        )
        return ctx


class TradingIntentCreateView(LoginRequiredMixin, CreateView):
    model = TradingIntent
    form_class = TradingIntentForm
    template_name = "trading/intent_form.html"
    success_url = reverse_lazy("trading:intent-list")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["portfolio"].queryset = self.request.user.portfolios.all()
        form.fields["broker_account"].queryset = self.request.user.broker_accounts.all()
        return form

    def form_valid(self, form):
        form.instance.user = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, "Intention de trading créée.")
        return response


class TradingIntentAnalyzeView(LoginRequiredMixin, View):
    def post(self, request, pk):
        intent = get_object_or_404(TradingIntent, pk=pk, user=request.user)
        try:
            IntentExecutionService.analyze(intent)
            messages.success(request, "Analyse IA terminée.")
        except Exception as exc:
            messages.error(request, f"Erreur lors de l'analyse : {exc}")
        return redirect("trading:intent-detail", pk=intent.pk)


class TradingIntentLaunchView(LoginRequiredMixin, View):
    def post(self, request, pk):
        intent = get_object_or_404(TradingIntent, pk=pk, user=request.user)
        try:
            IntentExecutionService.launch(intent)
            messages.success(request, "Mission de trading lancée.")
        except Exception as exc:
            messages.error(request, f"Impossible de lancer la mission : {exc}")
        return redirect("trading:intent-detail", pk=intent.pk)
