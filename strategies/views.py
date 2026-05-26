import json

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Avg, Q
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import (
    ListView,
    DetailView,
    CreateView,
    UpdateView,
    DeleteView,
    View,
)

from .models import (
    Strategy,
    Signal,
    StrategyRun,
    StrategyVersion,
    StrategyPrediction,
    StrategyPerformanceSnapshot,
)


class StrategyListView(LoginRequiredMixin, ListView):
    model = Strategy
    template_name = "strategies/strategy_list.html"
    context_object_name = "strategies"
    paginate_by = 20

    def get_queryset(self):
        qs = Strategy.objects.select_related("asset", "timeframe").order_by("name")

        status = self.request.GET.get("status")
        strategy_type = self.request.GET.get("strategy_type")
        asset_class = self.request.GET.get("asset_class")
        q = self.request.GET.get("q")

        if status:
            qs = qs.filter(status=status)
        if strategy_type:
            qs = qs.filter(strategy_type=strategy_type)
        if asset_class:
            qs = qs.filter(asset__asset_class=asset_class)
        if q:
            qs = qs.filter(name__icontains=q)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        strategies = self.get_queryset()

        ctx["summary"] = {
            "count": strategies.count(),
            "active_count": strategies.filter(is_active=True).count(),
            "autonomous_count": strategies.filter(is_autonomous=True).count(),
            "live_count": strategies.filter(status="LIVE").count(),
        }
        ctx["filters"] = {
            "status": self.request.GET.get("status", ""),
            "strategy_type": self.request.GET.get("strategy_type", ""),
            "asset_class": self.request.GET.get("asset_class", ""),
            "q": self.request.GET.get("q", ""),
        }
        return ctx


class StrategyDetailView(LoginRequiredMixin, DetailView):
    model = Strategy
    template_name = "strategies/strategy_detail.html"
    context_object_name = "strategy"

    def get_queryset(self):
        return Strategy.objects.select_related("asset", "timeframe")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        strategy = self.object

        signals = Signal.objects.filter(strategy=strategy).order_by("-created_at")[:50]
        runs = StrategyRun.objects.filter(strategy=strategy).order_by("-run_started_at")[:30]
        versions = StrategyVersion.objects.filter(strategy=strategy).order_by("-created_at")
        predictions = StrategyPrediction.objects.filter(strategy=strategy).order_by("-candle_time")[:20]
        perf_snapshots = list(
            StrategyPerformanceSnapshot.objects.filter(strategy=strategy)
            .order_by("snapshot_time")[:120]
        )

        aggregated = Signal.objects.filter(strategy=strategy).aggregate(
            total=Count("id"),
            avg_confidence=Avg("confidence"),
            executed=Count("id", filter=Q(status="EXECUTED")),
            approved=Count("id", filter=Q(status="APPROVED")),
            rejected=Count("id", filter=Q(status="REJECTED")),
        )

        context["signals"] = signals
        context["runs"] = runs
        context["versions"] = versions
        context["predictions"] = predictions
        context["performance_snapshots"] = perf_snapshots[::-1]
        context["stats"] = aggregated

        context["perf_chart_json"] = json.dumps({
            "labels": [s.snapshot_time.strftime("%d/%m") for s in context["performance_snapshots"]],
            "win_rate": [float(s.win_rate) for s in context["performance_snapshots"]],
            "avg_return": [float(s.avg_return) for s in context["performance_snapshots"]],
            "sharpe": [float(s.sharpe_ratio) for s in context["performance_snapshots"]],
            "drawdown": [float(s.max_drawdown) for s in context["performance_snapshots"]],
        })

        return context


class SignalListView(LoginRequiredMixin, ListView):
    model = Signal
    template_name = "strategies/signal_list.html"
    context_object_name = "signals"
    paginate_by = 30

    def get_queryset(self):
        qs = Signal.objects.select_related("strategy", "strategy__asset", "strategy__timeframe").order_by("-candle_time")

        status = self.request.GET.get("status")
        side = self.request.GET.get("side")
        strategy_id = self.request.GET.get("strategy")

        if status:
            qs = qs.filter(status=status)
        if side:
            qs = qs.filter(side=side)
        if strategy_id:
            qs = qs.filter(strategy_id=strategy_id)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["strategies"] = Strategy.objects.order_by("name")
        ctx["filters"] = {
            "status": self.request.GET.get("status", ""),
            "side": self.request.GET.get("side", ""),
            "strategy": self.request.GET.get("strategy", ""),
        }
        return ctx


class SignalDetailView(LoginRequiredMixin, DetailView):
    model = Signal
    template_name = "strategies/signal_detail.html"
    context_object_name = "signal"

    def get_queryset(self):
        return Signal.objects.select_related(
            "strategy",
            "strategy__asset",
            "strategy__timeframe",
            "strategy_run",
        )


class StrategyRunListView(LoginRequiredMixin, ListView):
    model = StrategyRun
    template_name = "strategies/strategy_run_list.html"
    context_object_name = "runs"
    paginate_by = 30

    def get_queryset(self):
        qs = StrategyRun.objects.select_related("strategy", "strategy__asset").order_by("-run_started_at")
        strategy_id = self.request.GET.get("strategy")
        status = self.request.GET.get("status")

        if strategy_id:
            qs = qs.filter(strategy_id=strategy_id)
        if status:
            qs = qs.filter(status=status)

        return qs


class StrategyRunDetailView(LoginRequiredMixin, DetailView):
    model = StrategyRun
    template_name = "strategies/strategy_run_detail.html"
    context_object_name = "run"

    def get_queryset(self):
        return StrategyRun.objects.select_related("strategy", "strategy__asset", "strategy__timeframe")


class StrategyToggleActiveView(LoginRequiredMixin, View):
    def post(self, request, pk):
        strategy = Strategy.objects.filter(pk=pk).first()
        if not strategy:
            messages.error(request, "Stratégie introuvable.")
            return redirect("strategy-list")

        strategy.is_active = not strategy.is_active
        strategy.save(update_fields=["is_active", "updated_at"])

        messages.success(
            request,
            f"Stratégie {'activée' if strategy.is_active else 'désactivée'} avec succès."
        )
        return redirect("strategy-detail", pk=strategy.pk)


class StrategyToggleAutonomousView(LoginRequiredMixin, View):
    def post(self, request, pk):
        strategy = Strategy.objects.filter(pk=pk).first()
        if not strategy:
            messages.error(request, "Stratégie introuvable.")
            return redirect("strategy-list")

        strategy.is_autonomous = not strategy.is_autonomous
        strategy.save(update_fields=["is_autonomous", "updated_at"])

        messages.success(
            request,
            f"Mode autonome {'activé' if strategy.is_autonomous else 'désactivé'}."
        )
        return redirect("strategy-detail", pk=strategy.pk)


class StrategySwitchStatusView(LoginRequiredMixin, View):
    def post(self, request, pk):
        strategy = Strategy.objects.filter(pk=pk).first()
        if not strategy:
            messages.error(request, "Stratégie introuvable.")
            return redirect("strategy-list")

        new_status = request.POST.get("status", "").strip()
        allowed = {"DRAFT", "BACKTEST", "PAPER", "LIVE", "PAUSED", "ARCHIVED", "FAILED"}

        if new_status not in allowed:
            messages.error(request, "Statut invalide.")
            return redirect("strategy-detail", pk=strategy.pk)

        strategy.status = new_status
        strategy.save(update_fields=["status", "updated_at"])
        messages.success(request, f"Statut mis à jour : {new_status}.")
        return redirect("strategy-detail", pk=strategy.pk)


class SignalApproveView(LoginRequiredMixin, View):
    def post(self, request, pk):
        signal = Signal.objects.select_related("strategy").filter(pk=pk).first()
        if not signal:
            messages.error(request, "Signal introuvable.")
            return redirect("signal-list")

        signal.status = "APPROVED"
        signal.approved_at = timezone.now()
        signal.save(update_fields=["status", "approved_at", "updated_at"])

        messages.success(request, "Signal approuvé.")
        return redirect("signal-detail", pk=signal.pk)


class SignalRejectView(LoginRequiredMixin, View):
    def post(self, request, pk):
        signal = Signal.objects.select_related("strategy").filter(pk=pk).first()
        if not signal:
            messages.error(request, "Signal introuvable.")
            return redirect("signal-list")

        signal.status = "REJECTED"
        signal.save(update_fields=["status", "updated_at"])

        messages.success(request, "Signal rejeté.")
        return redirect("signal-detail", pk=signal.pk)