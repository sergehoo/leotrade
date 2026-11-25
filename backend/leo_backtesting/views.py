from __future__ import annotations

import json
import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView

from core.outbox import OutboxService
from leo_backtesting.event_topics import BACKTEST_RUN_REQUESTED
from leo_backtesting.models import BacktestRun
from leo_backtesting.services import (
    ENGINE_VERSION,
    build_run_parameters,
    execution_assumptions_for,
)
from strategies.models import Strategy


log = logging.getLogger("lyneci.backtesting.views")


def _available_strategies_for(user):
    return Strategy.objects.visible_to(user).filter(is_active=True)


def _backtests_for_user(user):
    queryset = BacktestRun.objects.select_related(
        "strategy",
        "strategy__asset",
        "strategy__timeframe",
        "requested_by",
    )
    if user.is_staff:
        return queryset
    return queryset.filter(requested_by=user)


class BacktestListView(LoginRequiredMixin, ListView):
    model = BacktestRun
    template_name = "leo_backtesting/backtest_list.html"
    context_object_name = "backtests"
    paginate_by = 20

    def get_queryset(self):
        return _backtests_for_user(self.request.user).order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        full_queryset = self.get_queryset()
        context["count_total"] = full_queryset.count()
        context["count_done"] = full_queryset.filter(status="DONE").count()
        context["count_running"] = full_queryset.filter(
            status__in=["PENDING", "RUNNING"]
        ).count()
        context["count_failed"] = full_queryset.filter(status="FAILED").count()
        context["available_strategies"] = (
            _available_strategies_for(self.request.user)
            .select_related("asset", "timeframe")
            .order_by("name")[:50]
        )
        running_ids = full_queryset.filter(
            status__in=["PENDING", "RUNNING"]
        ).values_list("id", flat=True)
        context["running_backtest_ids"] = json.dumps(list(running_ids))
        return context


class BacktestDetailView(LoginRequiredMixin, DetailView):
    model = BacktestRun
    template_name = "leo_backtesting/backtest_detail.html"
    context_object_name = "backtest"

    def get_queryset(self):
        return _backtests_for_user(self.request.user)


class LaunchBacktestView(LoginRequiredMixin, View):
    def post(self, request, strategy_id):
        strategy = get_object_or_404(
            _available_strategies_for(request.user).select_related("asset", "timeframe"),
            pk=strategy_id,
        )
        assumptions = execution_assumptions_for(strategy)

        try:
            with transaction.atomic():
                today = timezone.localdate()
                run = BacktestRun.objects.create(
                    strategy=strategy,
                    requested_by=request.user,
                    name=f"BT - {strategy.name}",
                    start_date=today,
                    end_date=today,
                    initial_cash=assumptions["initial_cash"],
                    commission=assumptions["commission"],
                    spread=assumptions["spread"],
                    slippage=assumptions["slippage"],
                    parameters=build_run_parameters(strategy),
                    status="PENDING",
                    engine_version=ENGINE_VERSION,
                )
                OutboxService.enqueue(
                    topic=BACKTEST_RUN_REQUESTED,
                    aggregate_type="leo_backtesting.BacktestRun",
                    aggregate_id=run.id,
                    payload={"backtest_run_id": run.id},
                    idempotency_key=f"backtest:{run.id}:attempt:1",
                )
        except IntegrityError:
            run = BacktestRun.objects.filter(
                requested_by=request.user,
                strategy=strategy,
                status__in=["PENDING", "RUNNING"],
            ).first()
            if run is None:
                log.exception(
                    "backtest.launch.integrity_error user_id=%s strategy_id=%s",
                    request.user.id,
                    strategy.id,
                )
                messages.error(request, "Le backtest n’a pas pu être planifié.")
                return redirect("backtest-list")
            messages.warning(
                request,
                f"Le backtest #{run.id} est déjà en cours pour cette stratégie.",
            )
            return redirect("backtest-detail", pk=run.pk)

        messages.success(
            request,
            f"Backtest #{run.id} planifié. Le résultat apparaîtra automatiquement.",
        )
        return redirect("backtest-detail", pk=run.pk)


class BacktestStatusView(LoginRequiredMixin, View):
    def get(self, request, pk):
        run = get_object_or_404(_backtests_for_user(request.user), pk=pk)
        if not request.user.is_staff and run.requested_by_id != request.user.id:
            raise Http404
        return JsonResponse(
            {
                "id": run.id,
                "status": run.status,
                "name": run.name,
                "metrics": run.metrics or {},
                "failure_message": run.failure_message,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "updated_at": run.updated_at.isoformat() if run.updated_at else None,
            }
        )
