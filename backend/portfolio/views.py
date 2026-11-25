import json

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import (
    ListView, DetailView, CreateView, UpdateView, DeleteView, View
)

from .forms import PortfolioForm, PositionForm
from .models import Portfolio, Position
from .services import PortfolioService
from .broker_import import BrokerImportService


class PortfolioListView(LoginRequiredMixin, ListView):
    model = Portfolio
    template_name = "portfolio/portfolio_list.html"
    context_object_name = "portfolios"

    def get_queryset(self):
        return (
            Portfolio.objects
            .filter(user=self.request.user)
            .select_related("broker_account")
            .order_by("name")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        portfolios = self.get_queryset()
        ctx["summary"] = {
            "count": portfolios.count(),
            "default": portfolios.filter(is_default=True).first(),
            "active_count": portfolios.filter(is_active=True).count(),
            "total_equity": float(sum((p.equity for p in portfolios), start=0)),
        }
        return ctx


class PortfolioDetailView(LoginRequiredMixin, DetailView):
    model = Portfolio
    template_name = "portfolio/portfolio_detail.html"
    context_object_name = "portfolio"

    def get_queryset(self):
        return Portfolio.objects.filter(user=self.request.user).select_related("broker_account")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        portfolio = self.object

        PortfolioService.refresh_portfolio_metrics(portfolio)

        open_positions = portfolio.positions.filter(
            status__in=["OPEN", "PARTIALLY_CLOSED"]
        ).select_related("asset")
        closed_positions = portfolio.positions.filter(status="CLOSED").select_related("asset")[:10]
        allocations = portfolio.allocations.select_related("asset")
        snapshots = list(portfolio.snapshots.order_by("snapshot_time")[:120])

        asset_exposure = PortfolioService.asset_class_exposure(portfolio)
        corr_rows = PortfolioService.position_correlation_matrix(portfolio, timeframe_code="1d", lookback_bars=60)

        ctx["open_positions"] = open_positions
        ctx["closed_positions"] = closed_positions
        ctx["allocations"] = allocations
        ctx["snapshots"] = snapshots[::-1]
        ctx["ledger_entries"] = portfolio.ledger_entries.all()[:20]

        ctx["stats"] = {
            "open_positions_count": portfolio.positions.filter(status__in=["OPEN", "PARTIALLY_CLOSED"]).count(),
            "closed_positions_count": portfolio.positions.filter(status="CLOSED").count(),
            "unrealized_pnl": portfolio.unrealized_pnl,
            "realized_pnl": portfolio.realized_pnl,
            "equity": portfolio.equity,
            "balance": portfolio.current_balance,
            "available_cash": portfolio.available_cash,
            "locked_cash": portfolio.locked_cash,
            "margin_used": portfolio.margin_used,
            "drawdown": portfolio.current_drawdown_percent,
            "max_drawdown": portfolio.max_drawdown_percent,
        }

        ctx["equity_chart_json"] = json.dumps({
            "labels": [s.snapshot_time.strftime("%d/%m %H:%M") for s in ctx["snapshots"]],
            "equity": [float(s.equity) for s in ctx["snapshots"]],
            "balance": [float(s.balance) for s in ctx["snapshots"]],
            "available_cash": [float(s.available_cash) for s in ctx["snapshots"]],
            "locked_cash": [float(s.locked_cash) for s in ctx["snapshots"]],
            "drawdown": [float(s.drawdown_percent) for s in ctx["snapshots"]],
        })

        ctx["performance_chart_json"] = json.dumps({
            "labels": [s.snapshot_time.strftime("%d/%m") for s in ctx["snapshots"]],
            "daily": [float(s.daily_return_percent) for s in ctx["snapshots"]],
            "monthly": [float(s.monthly_return_percent) for s in ctx["snapshots"]],
        })

        ctx["asset_exposure_json"] = json.dumps({
            "labels": [row["asset_class"] for row in asset_exposure],
            "values": [row["value"] for row in asset_exposure],
            "percents": [row["percent"] for row in asset_exposure],
        })

        ctx["correlation_rows"] = corr_rows
        return ctx


class PortfolioCreateView(LoginRequiredMixin, CreateView):
    model = Portfolio
    form_class = PortfolioForm
    template_name = "portfolio/portfolio_form.html"
    success_url = reverse_lazy("portfolio-list")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["broker_account"].queryset = self.request.user.broker_accounts.all()
        return form

    def form_valid(self, form):
        form.instance.user = self.request.user
        response = super().form_valid(form)
        PortfolioService.refresh_portfolio_metrics(self.object)
        messages.success(self.request, "Portfolio créé avec succès.")
        return response


class PortfolioUpdateView(LoginRequiredMixin, UpdateView):
    model = Portfolio
    form_class = PortfolioForm
    template_name = "portfolio/portfolio_form.html"
    success_url = reverse_lazy("portfolio-list")

    def get_queryset(self):
        return Portfolio.objects.filter(user=self.request.user)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["broker_account"].queryset = self.request.user.broker_accounts.all()
        return form

    def form_valid(self, form):
        response = super().form_valid(form)
        PortfolioService.refresh_portfolio_metrics(self.object)
        messages.success(self.request, "Portfolio mis à jour.")
        return response


class PortfolioDeleteView(LoginRequiredMixin, DeleteView):
    model = Portfolio
    template_name = "portfolio/portfolio_confirm_delete.html"
    success_url = reverse_lazy("portfolio-list")

    def get_queryset(self):
        return Portfolio.objects.filter(user=self.request.user)


class PortfolioSetDefaultView(LoginRequiredMixin, View):
    def post(self, request, pk):
        portfolio = Portfolio.objects.filter(user=request.user, pk=pk).first()
        if not portfolio:
            messages.error(request, "Portfolio introuvable.")
            return redirect("portfolio-list")

        PortfolioService.set_default_portfolio(portfolio)
        messages.success(request, f"{portfolio.name} défini comme portfolio par défaut.")
        return redirect("portfolio-list")


class PortfolioSnapshotCreateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        portfolio = Portfolio.objects.filter(user=request.user, pk=pk).first()
        if not portfolio:
            messages.error(request, "Portfolio introuvable.")
            return redirect("portfolio-list")

        PortfolioService.create_snapshot(portfolio)
        messages.success(request, "Snapshot créé.")
        return redirect("portfolio-detail", pk=portfolio.pk)


class PortfolioImportLiveView(LoginRequiredMixin, View):
    def post(self, request, pk):
        portfolio = Portfolio.objects.filter(user=request.user, pk=pk).first()
        if not portfolio:
            messages.error(request, "Portfolio introuvable.")
            return redirect("portfolio-list")

        try:
            imported = BrokerImportService.import_live_positions(portfolio)
            PortfolioService.create_snapshot(portfolio)
            messages.success(request, f"{len(imported)} positions importées depuis le broker.")
        except Exception as exc:
            messages.error(request, f"Import live impossible : {exc}")

        return redirect("portfolio-detail", pk=portfolio.pk)


class PositionCreateView(LoginRequiredMixin, CreateView):
    model = Position
    form_class = PositionForm
    template_name = "portfolio/position_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.portfolio = Portfolio.objects.filter(user=request.user, pk=self.kwargs["portfolio_pk"]).first()
        if not self.portfolio:
            messages.error(request, "Portfolio introuvable.")
            return redirect("portfolio-list")
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse_lazy("portfolio-detail", kwargs={"pk": self.portfolio.pk})

    def form_valid(self, form):
        form.instance.portfolio = self.portfolio
        form.instance.broker_account = self.portfolio.broker_account
        response = super().form_valid(form)
        PortfolioService.refresh_portfolio_metrics(self.portfolio)
        messages.success(self.request, "Position ajoutée.")
        return response


class PositionUpdateView(LoginRequiredMixin, UpdateView):
    model = Position
    form_class = PositionForm
    template_name = "portfolio/position_form.html"

    def get_queryset(self):
        return Position.objects.filter(portfolio__user=self.request.user).select_related("portfolio", "asset")

    def get_success_url(self):
        return reverse_lazy("portfolio-detail", kwargs={"pk": self.object.portfolio.pk})

    def form_valid(self, form):
        form.instance.broker_account = form.instance.portfolio.broker_account
        response = super().form_valid(form)
        PortfolioService.refresh_portfolio_metrics(self.object.portfolio)
        messages.success(self.request, "Position mise à jour.")
        return response


class PositionDeleteView(LoginRequiredMixin, DeleteView):
    model = Position
    template_name = "portfolio/position_confirm_delete.html"

    def get_queryset(self):
        return Position.objects.filter(portfolio__user=self.request.user).select_related("portfolio")

    def get_success_url(self):
        return reverse_lazy("portfolio-detail", kwargs={"pk": self.object.portfolio.pk})

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        portfolio = self.object.portfolio
        response = super().delete(request, *args, **kwargs)
        PortfolioService.refresh_portfolio_metrics(portfolio)
        messages.success(request, "Position supprimée.")
        return response