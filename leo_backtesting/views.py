"""
leo_backtesting/views.py
========================

Vues backtest sécurisées + lancement asynchrone via Celery.

Avant :
  - BacktestListView retournait `.all()` → fuite de tous les backtests entre users
  - LaunchBacktestView appelait `run_backtest()` synchroniquement dans la vue
    HTTP → blocage 5-30s + timeout possible
  - Pas de check d'ownership de la stratégie

Après :
  - Filtrage strict par user via strategy__user
  - Lancement async via `run_backtest_task.delay(bt_id)` (worker Celery)
  - Statut PENDING → RUNNING → DONE / FAILED suivi en live (poll status JSON)
"""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import DetailView, ListView

from leo_backtesting.models import BacktestRun
from strategies.models import Strategy


log = logging.getLogger("leotrade.backtesting.views")


def _user_owns_strategy(user, strategy: Strategy) -> bool:
    """
    Strategy peut être attachée à un user direct, à un portfolio (qui a user),
    ou être globale. On accepte l'ownership transitif.
    Staff = accès total.
    """
    if getattr(strategy, "user_id", None) and strategy.user_id == user.id:
        return True
    pf = getattr(strategy, "portfolio", None)
    if pf and getattr(pf, "user_id", None) == user.id:
        return True
    return getattr(user, "is_staff", False)


class BacktestListView(LoginRequiredMixin, ListView):
    """
    Liste les backtests de l'utilisateur (via les stratégies qu'il possède).
    """
    model = BacktestRun
    template_name = "leo_backtesting/backtest_list.html"
    context_object_name = "backtests"
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user
        for filter_kwargs in (
            {"strategy__user": user},
            {"strategy__portfolio__user": user},
        ):
            try:
                qs = BacktestRun.objects.filter(**filter_kwargs)
                qs.exists()  # vérifie que le filtre est valide pour le schéma
                return qs.select_related(
                    "strategy", "strategy__asset", "strategy__timeframe"
                ).order_by("-created_at")
            except Exception:
                continue
        if user.is_staff:
            return BacktestRun.objects.select_related("strategy").order_by("-created_at")
        return BacktestRun.objects.none()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        full_qs = self.get_queryset()
        ctx["count_total"] = full_qs.count()
        ctx["count_done"] = full_qs.filter(status="DONE").count()
        ctx["count_running"] = full_qs.filter(status__in=["PENDING", "RUNNING"]).count()
        ctx["count_failed"] = full_qs.filter(status="FAILED").count()

        # Stratégies dispo pour le bouton "Lancer un backtest"
        try:
            user_strategies = Strategy.objects.filter(user=self.request.user)
            user_strategies.exists()
        except Exception:
            try:
                user_strategies = Strategy.objects.filter(portfolio__user=self.request.user)
            except Exception:
                user_strategies = Strategy.objects.none()
        ctx["available_strategies"] = user_strategies.select_related(
            "asset", "timeframe"
        )[:50]
        return ctx


class BacktestDetailView(LoginRequiredMixin, DetailView):
    model = BacktestRun
    template_name = "leo_backtesting/backtest_detail.html"
    context_object_name = "backtest"

    def get_queryset(self):
        user = self.request.user
        for filter_kwargs in (
            {"strategy__user": user},
            {"strategy__portfolio__user": user},
        ):
            try:
                qs = BacktestRun.objects.filter(**filter_kwargs)
                qs.exists()
                return qs.select_related("strategy")
            except Exception:
                continue
        if user.is_staff:
            return BacktestRun.objects.select_related("strategy")
        return BacktestRun.objects.none()


class LaunchBacktestView(LoginRequiredMixin, View):
    """
    Lance un backtest de manière ASYNC via Celery.

    POST /backtests/launch/<strategy_id>/
      → vérifie ownership
      → crée BacktestRun(status=PENDING)
      → délègue à run_backtest_task.delay(bt_id)
      → si Celery indispo → fallback synchrone (avec warning)
    """

    def post(self, request, strategy_id):
        strategy = get_object_or_404(Strategy, pk=strategy_id)

        if not _user_owns_strategy(request.user, strategy):
            log.warning(
                "backtest.launch.forbidden user_id=%s strategy_id=%s",
                request.user.id, strategy_id,
            )
            messages.error(request, "Tu n'as pas accès à cette stratégie.")
            return redirect("backtest-list")

        # Crée le run en PENDING (visible immédiatement dans la liste)
        from datetime import date
        bt = BacktestRun.objects.create(
            strategy=strategy,
            name=f"BT - {strategy.name}",
            start_date=date.today(),
            end_date=date.today(),
            status="PENDING",
            metrics={},
        )

        try:
            from leo_backtesting.tasks import run_backtest_task
            run_backtest_task.delay(bt.id)
            messages.success(
                request,
                f"Backtest #{bt.id} en file d'attente. Le résultat apparaîtra dès la fin du calcul.",
            )
        except Exception as exc:
            # Fallback synchrone si Celery indispo (dev sans worker)
            log.warning(
                "backtest.celery_unavailable fallback_sync strategy_id=%s err=%s",
                strategy_id, exc,
            )
            try:
                from leo_backtesting.services import run_backtest
                _resync_to_existing_run(bt, run_backtest(strategy))
                messages.success(request, f"Backtest #{bt.id} terminé (mode synchrone).")
            except Exception as exc2:
                bt.status = "FAILED"
                bt.metrics = {"error": str(exc2)}
                bt.save(update_fields=["status", "metrics"])
                messages.error(request, f"Échec backtest : {exc2}")

        return redirect("backtest-detail", pk=bt.pk)


def _resync_to_existing_run(target: BacktestRun, source: BacktestRun) -> None:
    """
    Quand le fallback synchrone est utilisé, le service `run_backtest`
    crée son propre BacktestRun. Pour éviter d'avoir deux objets, on copie
    les résultats dans le PENDING déjà créé et on supprime le doublon.
    """
    if not source or source.id == target.id:
        return
    target.status = source.status
    target.metrics = source.metrics or {}
    target.equity_curve = source.equity_curve or []
    target.trades_log = source.trades_log or []
    target.start_date = source.start_date or target.start_date
    target.end_date = source.end_date or target.end_date
    target.initial_cash = source.initial_cash
    target.commission = source.commission
    target.save()
    try:
        source.delete()
    except Exception:
        pass


class BacktestStatusView(LoginRequiredMixin, View):
    """
    Endpoint AJAX pour poller le statut d'un backtest en cours.
    GET /backtests/<id>/status/  → JSON {status, metrics, ...}
    """

    def get(self, request, pk):
        bt = get_object_or_404(BacktestRun, pk=pk)
        if not _user_owns_strategy(request.user, bt.strategy):
            raise Http404
        return JsonResponse({
            "id": bt.id,
            "status": bt.status,
            "name": bt.name,
            "metrics": bt.metrics or {},
            "started_at": bt.created_at.isoformat() if bt.created_at else None,
            "updated_at": bt.updated_at.isoformat() if bt.updated_at else None,
        })
