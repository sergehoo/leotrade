import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Avg, Q
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
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

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _health_score(win_rate, sharpe, drawdown, avg_conf, signal_activity_7d):
        """
        Score de santé 0-100 synthétisant les métriques clés.
        Composantes :
          - win_rate      : 0-40 pts  (40 pts si ≥ 0.60)
          - sharpe        : 0-30 pts  (30 pts si ≥ 2.0)
          - drawdown      : 0-20 pts  (20 pts si ≤ 5 %)
          - activité 7j   : 0-10 pts  (≥ 3 signaux = 10 pts)
        """
        score = 0.0
        # win rate
        score += min(win_rate / 0.60, 1.0) * 40
        # sharpe
        score += min(max(sharpe, 0) / 2.0, 1.0) * 30
        # drawdown (inverse : moins c'est mieux)
        if drawdown <= 0:
            score += 20
        else:
            score += max(0, 1 - drawdown / 20) * 20
        # activité récente
        score += min(signal_activity_7d / 3, 1.0) * 10
        return round(min(score, 100), 1)

    @staticmethod
    def _interpret(value, thresholds, labels):
        """Renvoie (label, css_class) en fonction des seuils."""
        for i, t in enumerate(thresholds):
            if value < t:
                return labels[i]
        return labels[-1]

    # ------------------------------------------------------------------ context
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        strategy = self.object
        now = timezone.now()

        # ── Signaux ──────────────────────────────────────────────────────────
        all_signals_agg = Signal.objects.filter(strategy=strategy).aggregate(
            total=Count("id"),
            avg_confidence=Avg("confidence"),
            executed=Count("id", filter=Q(status="EXECUTED")),
            approved=Count("id", filter=Q(status="APPROVED")),
            rejected=Count("id", filter=Q(status="REJECTED")),
            expired=Count("id", filter=Q(status="EXPIRED")),
            new=Count("id", filter=Q(status="NEW")),
            buy=Count("id", filter=Q(side="BUY")),
            sell=Count("id", filter=Q(side="SELL")),
        )
        signals_24h = Signal.objects.filter(
            strategy=strategy, created_at__gte=now - timedelta(hours=24)
        ).count()
        signals_7d = Signal.objects.filter(
            strategy=strategy, created_at__gte=now - timedelta(days=7)
        ).count()

        recent_signals = Signal.objects.filter(strategy=strategy).order_by("-created_at")[:30]

        # ── Runs ─────────────────────────────────────────────────────────────
        runs = StrategyRun.objects.filter(strategy=strategy).order_by("-run_started_at")[:30]
        run_agg = StrategyRun.objects.filter(strategy=strategy).aggregate(
            total=Count("id"),
            succeeded=Count("id", filter=Q(status="SUCCEEDED")),
            failed=Count("id", filter=Q(status="FAILED")),
        )
        run_success_rate = 0.0
        if run_agg["total"]:
            run_success_rate = round(run_agg["succeeded"] / run_agg["total"] * 100, 1)

        # ── Performance snapshots ─────────────────────────────────────────────
        perf_snapshots = list(
            StrategyPerformanceSnapshot.objects.filter(strategy=strategy)
            .order_by("snapshot_time")[:120]
        )
        latest_snap = perf_snapshots[-1] if perf_snapshots else None
        win_rate = float(latest_snap.win_rate) if latest_snap else 0.0
        sharpe   = float(latest_snap.sharpe_ratio) if latest_snap else 0.0
        drawdown = float(latest_snap.max_drawdown) if latest_snap else 0.0
        avg_ret  = float(latest_snap.avg_return) if latest_snap else 0.0

        # ── Score de santé ────────────────────────────────────────────────────
        health = self._health_score(
            win_rate=win_rate,
            sharpe=sharpe,
            drawdown=drawdown,
            avg_conf=float(all_signals_agg["avg_confidence"] or 0),
            signal_activity_7d=signals_7d,
        )
        if health >= 75:
            health_label, health_class = "Excellente", "text-emerald-400"
        elif health >= 55:
            health_label, health_class = "Bonne", "text-blue-400"
        elif health >= 35:
            health_label, health_class = "Moyenne", "text-amber-400"
        else:
            health_label, health_class = "Faible", "text-red-400"

        # ── Interprétations des métriques ─────────────────────────────────────
        def _wr_label(v):
            if v >= 0.65: return ("Fort ✅", "text-emerald-400")
            if v >= 0.50: return ("Modéré ⚡", "text-amber-400")
            return ("Faible ❌", "text-red-400")

        def _sharpe_label(v):
            if v >= 2.0: return ("Excellent ✅", "text-emerald-400")
            if v >= 1.0: return ("Bon ⚡", "text-blue-400")
            if v >= 0.5: return ("Acceptable", "text-amber-400")
            return ("Insuffisant ❌", "text-red-400")

        def _dd_label(v):
            if v <= 5:  return ("Faible ✅", "text-emerald-400")
            if v <= 15: return ("Modéré ⚡", "text-amber-400")
            return ("Élevé ❌", "text-red-400")

        def _conf_label(v):
            if v >= 0.75: return ("Haute ✅", "text-emerald-400")
            if v >= 0.55: return ("Moyenne ⚡", "text-amber-400")
            return ("Basse ❌", "text-red-400")

        metrics_interpretation = {
            "win_rate":   {"value": win_rate,   "pct": f"{win_rate*100:.1f}%",   **dict(zip(["label","cls"], _wr_label(win_rate)))},
            "sharpe":     {"value": sharpe,     "pct": f"{sharpe:.2f}",           **dict(zip(["label","cls"], _sharpe_label(sharpe)))},
            "drawdown":   {"value": drawdown,   "pct": f"{drawdown:.1f}%",        **dict(zip(["label","cls"], _dd_label(drawdown)))},
            "avg_conf":   {"value": float(all_signals_agg["avg_confidence"] or 0),
                           "pct": f"{float(all_signals_agg['avg_confidence'] or 0)*100:.1f}%",
                           **dict(zip(["label","cls"], _conf_label(float(all_signals_agg["avg_confidence"] or 0))))},
            "avg_return": {"value": avg_ret,    "pct": f"{avg_ret:.3f}"},
        }

        # ── Signal breakdown pour donut chart ─────────────────────────────────
        signal_breakdown_json = json.dumps({
            "labels":  ["Exécutés", "Approuvés", "Rejetés", "Expirés", "Nouveaux"],
            "values":  [
                all_signals_agg["executed"] or 0,
                all_signals_agg["approved"] or 0,
                all_signals_agg["rejected"] or 0,
                all_signals_agg["expired"]  or 0,
                all_signals_agg["new"]      or 0,
            ],
            "colors": ["#00ff9d", "#3b82f6", "#ff4d6d", "#6b7280", "#ffb703"],
        })

        # ── Graphique perf ─────────────────────────────────────────────────────
        perf_chart_json = json.dumps({
            "labels":    [s.snapshot_time.strftime("%d/%m") for s in perf_snapshots],
            "win_rate":  [float(s.win_rate) for s in perf_snapshots],
            "avg_return":[float(s.avg_return) for s in perf_snapshots],
            "sharpe":    [float(s.sharpe_ratio) for s in perf_snapshots],
            "drawdown":  [float(s.max_drawdown) for s in perf_snapshots],
        })

        # ── Entry / exit rules lisibles ────────────────────────────────────────
        def _rules_to_list(rules_dict):
            """Convertit le JSON rules en liste de textes compréhensibles."""
            if not rules_dict or not isinstance(rules_dict, dict):
                return []
            items = []
            for key, val in rules_dict.items():
                if isinstance(val, dict):
                    items.append(f"{key}: " + ", ".join(f"{k}={v}" for k, v in val.items()))
                else:
                    items.append(f"{key}: {val}")
            return items

        entry_rules_list = _rules_to_list(strategy.entry_rules)
        exit_rules_list  = _rules_to_list(strategy.exit_rules)

        # ── Backtest le plus récent ───────────────────────────────────────────
        try:
            from leo_backtesting.models import BacktestRun
            latest_backtest = (
                BacktestRun.objects.filter(strategy=strategy)
                .order_by("-created_at").first()
            )
        except Exception:
            latest_backtest = None

        # ── Versions ──────────────────────────────────────────────────────────
        versions = StrategyVersion.objects.filter(strategy=strategy).order_by("-created_at")

        # ── Prédictions récentes ───────────────────────────────────────────────
        predictions = StrategyPrediction.objects.filter(strategy=strategy).order_by("-candle_time")[:10]

        context.update({
            # Données brutes
            "signals": recent_signals,
            "runs": runs,
            "versions": versions,
            "predictions": predictions,
            "stats": all_signals_agg,
            "run_agg": run_agg,
            "run_success_rate": run_success_rate,
            "signals_24h": signals_24h,
            "signals_7d": signals_7d,
            "latest_snap": latest_snap,
            "latest_backtest": latest_backtest,
            # Santé globale
            "health": health,
            "health_label": health_label,
            "health_class": health_class,
            # Interprétations
            "metrics": metrics_interpretation,
            # Règles lisibles
            "entry_rules_list": entry_rules_list,
            "exit_rules_list": exit_rules_list,
            # JSON pour les charts
            "perf_chart_json": perf_chart_json,
            "signal_breakdown_json": signal_breakdown_json,
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


@login_required
def strategy_list_api(request):
    """Live JSON endpoint for strategies."""
    cutoff = timezone.now() - timedelta(hours=24)

    strategies = Strategy.objects.annotate(
        signal_count=Count("signals", distinct=True),
        recent_signals=Count(
            "signals",
            filter=Q(signals__created_at__gte=cutoff),
            distinct=True,
        ),
    ).select_related("asset", "timeframe").order_by("-is_active", "name")

    data = []
    for s in strategies:
        data.append({
            "id": s.id,
            "name": s.name,
            "strategy_type": s.strategy_type,
            "status": s.status,
            "is_active": s.is_active,
            "is_autonomous": s.is_autonomous,
            "symbol": s.asset.symbol if s.asset else "—",
            "timeframe": s.timeframe.code if s.timeframe else "—",
            "signal_count": s.signal_count,
            "recent_signals": s.recent_signals,
            "last_signal_at": s.last_signal_at.strftime("%d/%m %H:%M") if s.last_signal_at else None,
        })

    return JsonResponse({"strategies": data, "count": len(data)})
