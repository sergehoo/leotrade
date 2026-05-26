from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db import connection
from django.db.utils import OperationalError, ProgrammingError
from django.http import JsonResponse
from django.shortcuts import redirect, get_object_or_404, render
from django.utils import timezone
from django.views import View
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from dashboard.form import KYCSubmissionForm
from dashboard.models import KYCProfile
from execution.models import Order
from leo_backtesting.models import BacktestRun
from market.models import Candle
from portfolio.models import Portfolio, Position
from strategies.models import Signal


def _existing_table_columns(table_name: str) -> set[str]:
    try:
        with connection.cursor() as cursor:
            description = connection.introspection.get_table_description(cursor, table_name)
        return {col.name for col in description}
    except Exception:
        return set()


def _safe_decimal(value, default="0") -> Decimal:
    try:
        if value is None or value == "":
            return Decimal(default)
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _safe_float(value, default=0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError, InvalidOperation):
        return float(default)


def _portfolio_safe_queryset():
    """
    Ne sélectionne que les colonnes réellement présentes en base pour éviter
    les ProgrammingError quand le modèle a évolué plus vite que la table SQL.
    """
    existing = _existing_table_columns("portfolio_portfolio")

    wanted = [
        "id",
        "user_id",
        "broker_account_id",
        "name",
        "description",
        "base_currency",
        "starting_balance",
        "current_balance",
        "available_cash",
        "locked_cash",
        "equity",
        "unrealized_pnl",
        "realized_pnl",
        "margin_used",
        "max_equity",
        "current_drawdown_percent",
        "max_drawdown_percent",
        "is_active",
        "is_default",
        "last_reconciled_at",
        "notes",
    ]
    safe_fields = [f for f in wanted if f in existing]

    qs = Portfolio.objects.select_related("broker_account")
    if safe_fields:
        qs = qs.only(
            *safe_fields,
            "broker_account__id",
            "broker_account__name",
            "broker_account__broker",
            "broker_account__mode",
        )
    return qs


def _hydrate_portfolio_defaults(portfolio):
    """
    Évite les accès à des champs différés ou absents en base en injectant des
    valeurs par défaut sur l'instance.
    """
    if not portfolio:
        return None

    defaults = {
        "available_cash": Decimal("0.00"),
        "locked_cash": Decimal("0.00"),
        "equity": getattr(portfolio, "current_balance", Decimal("0.00")) or Decimal("0.00"),
        "unrealized_pnl": Decimal("0.00"),
        "realized_pnl": Decimal("0.00"),
        "margin_used": Decimal("0.00"),
        "max_equity": getattr(portfolio, "current_balance", Decimal("0.00")) or Decimal("0.00"),
        "current_drawdown_percent": 0.0,
        "max_drawdown_percent": 0.0,
        "notes": "",
    }

    existing = _existing_table_columns("portfolio_portfolio")

    for field_name, default_value in defaults.items():
        if field_name not in existing:
            setattr(portfolio, field_name, default_value)

    return portfolio


def _safe_get_default_portfolio(user):
    if not user or not user.is_authenticated:
        return None

    try:
        portfolio = (
            _portfolio_safe_queryset()
            .filter(user=user)
            .first()
        )
        return _hydrate_portfolio_defaults(portfolio)
    except (ProgrammingError, OperationalError):
        return None


class LandingPageView(TemplateView):
    template_name = "landing/home.html"


class HedgeFundDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/fund_dashboard.html"
    login_url = "account_login"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        portfolio = _safe_get_default_portfolio(self.request.user)
        context["portfolio"] = portfolio

        if portfolio:
            open_positions_qs = (
                Position.objects
                .filter(portfolio=portfolio, status__in=["OPEN", "PARTIALLY_CLOSED"])
                .select_related("asset", "broker_account")
                .order_by("-opened_at")
            )

            recent_orders_qs = (
                Order.objects
                .filter(portfolio=portfolio)
                .select_related("signal", "asset", "broker_account")
                .order_by("-created_at")[:12]
            )

            orders_qs = Order.objects.filter(portfolio=portfolio)

            realized_pnl = _safe_decimal(getattr(portfolio, "realized_pnl", 0))
            unrealized_pnl = _safe_decimal(getattr(portfolio, "unrealized_pnl", 0))
            total_pnl = realized_pnl + unrealized_pnl
            balance = _safe_decimal(getattr(portfolio, "current_balance", 0))
            equity = _safe_decimal(getattr(portfolio, "equity", balance))
            available_cash = _safe_decimal(getattr(portfolio, "available_cash", balance))
            locked_cash = _safe_decimal(getattr(portfolio, "locked_cash", 0))

            pnl_percent = Decimal("0")
            if balance > 0:
                pnl_percent = (total_pnl / balance) * Decimal("100")

            long_count = open_positions_qs.filter(side="LONG").count()
            short_count = open_positions_qs.filter(side="SHORT").count()

            winners_count = 0
            losers_count = 0
            for p in open_positions_qs:
                pnl_value = _safe_decimal(getattr(p, "pnl", 0))
                if pnl_value > 0:
                    winners_count += 1
                elif pnl_value < 0:
                    losers_count += 1

            context["open_positions"] = open_positions_qs
            context["recent_orders"] = recent_orders_qs
            context["stats"] = {
                "balance": balance,
                "equity": equity,
                "available_cash": available_cash,
                "locked_cash": locked_cash,
                "realized_pnl": realized_pnl,
                "unrealized_pnl": unrealized_pnl,
                "total_pnl": total_pnl,
                "pnl_percent": pnl_percent,
                "open_positions_count": open_positions_qs.count(),
                "orders_count": orders_qs.count(),
                "filled_orders": orders_qs.filter(status="FILLED").count(),
                "submitted_orders": orders_qs.filter(status__in=["SUBMITTED", "PARTIALLY_FILLED"]).count(),
                "long_positions_count": long_count,
                "short_positions_count": short_count,
                "winners_count": winners_count,
                "losers_count": losers_count,
            }
        else:
            context["open_positions"] = []
            context["recent_orders"] = []
            context["stats"] = {
                "balance": Decimal("0"),
                "equity": Decimal("0"),
                "available_cash": Decimal("0"),
                "locked_cash": Decimal("0"),
                "realized_pnl": Decimal("0"),
                "unrealized_pnl": Decimal("0"),
                "total_pnl": Decimal("0"),
                "pnl_percent": Decimal("0"),
                "open_positions_count": 0,
                "orders_count": 0,
                "filled_orders": 0,
                "submitted_orders": 0,
                "long_positions_count": 0,
                "short_positions_count": 0,
                "winners_count": 0,
                "losers_count": 0,
            }

        context["recent_signals"] = (
            Signal.objects
            .select_related("strategy", "strategy__asset")
            .order_by("-created_at")[:10]
        )

        context["backtests"] = BacktestRun.objects.order_by("-created_at")[:5]
        return context


class HedgeFundDashboardLiveDataView(LoginRequiredMixin, View):
    """
    Endpoint AJAX pour alimenter le dashboard live.

    Corrige :
    - prix live depuis la dernière candle valide
    - PnL recalculé côté serveur
    - déduplication des candles
    - chart trié proprement
    - neutralisation du faux PnL linéaire pour les actifs synthétiques Deriv
    - accès safe au Portfolio pendant une transition de migrations
    - enrichissement des stats live pour le dashboard premium
    """

    DEFAULT_CHART_POINTS = 40
    SYNTHETIC_PREFIXES = (
        "R_",
        "JD",
        "CRASH",
        "BOOM",
        "VOL",
        "STEP",
        "RDBEAR",
        "RDBULL",
    )

    @staticmethod
    def _to_decimal(value, default="0") -> Decimal:
        return _safe_decimal(value, default)

    @staticmethod
    def _to_float(value, default=0.0) -> float:
        return _safe_float(value, default)

    @staticmethod
    def _clamp_decimal(value: Decimal, minimum: Decimal, maximum: Decimal) -> Decimal:
        return max(minimum, min(maximum, value))

    @classmethod
    def _is_synthetic_symbol(cls, symbol: str) -> bool:
        if not symbol:
            return False
        symbol_upper = str(symbol).upper().strip()
        return any(symbol_upper.startswith(prefix) for prefix in cls.SYNTHETIC_PREFIXES)

    @classmethod
    def _get_clean_chart_for_asset(cls, asset, limit=40):
        if not asset:
            return [], []

        raw_rows = list(
            Candle.objects
            .filter(asset=asset)
            .order_by("-open_time", "-id")[:max(limit * 3, limit)]
        )

        dedup = {}
        for candle in raw_rows:
            open_time = getattr(candle, "open_time", None)
            if open_time is not None and open_time not in dedup:
                dedup[open_time] = candle

        clean_rows = sorted(dedup.values(), key=lambda c: c.open_time)[-limit:]

        chart = [
            {
                "t": c.open_time.isoformat() if getattr(c, "open_time", None) else None,
                "o": cls._to_float(getattr(c, "open", None)),
                "h": cls._to_float(getattr(c, "high", None)),
                "l": cls._to_float(getattr(c, "low", None)),
                "c": cls._to_float(getattr(c, "close", None)),
            }
            for c in clean_rows
        ]

        return clean_rows, chart

    @classmethod
    def _get_live_price(cls, pos, chart_rows):
        if chart_rows:
            last_row = chart_rows[-1]
            last_close = cls._to_decimal(getattr(last_row, "close", None), default="0")
            if last_close > 0:
                return last_close

        current_price = cls._to_decimal(getattr(pos, "current_price", None), default="0")
        if current_price > 0:
            return current_price

        entry_price = cls._to_decimal(getattr(pos, "entry_price", None), default="0")
        if entry_price > 0:
            return entry_price

        return Decimal("0")

    @classmethod
    def _get_position_pnl_value(cls, pos):
        candidate_fields = [
            "unrealized_pnl",
            "pnl",
            "floating_pnl",
            "profit",
        ]

        for field_name in candidate_fields:
            if hasattr(pos, field_name):
                value = cls._to_decimal(getattr(pos, field_name, None), default="0")
                if value != 0:
                    return value

        return Decimal("0")

    @classmethod
    def _compute_pnl(cls, pos, side, symbol, entry_price, current_price, quantity):
        pnl_value = Decimal("0")
        pnl_percent = Decimal("0")

        if entry_price <= 0 or current_price <= 0:
            return pnl_value, pnl_percent

        is_synthetic = cls._is_synthetic_symbol(symbol)

        if is_synthetic:
            stored_pnl = cls._get_position_pnl_value(pos)
            pnl_value = stored_pnl

            if entry_price > 0 and quantity > 0:
                try:
                    notional = entry_price * quantity
                    if notional > 0:
                        pnl_percent = (pnl_value / notional) * Decimal("100")
                except Exception:
                    pnl_percent = Decimal("0")

            return pnl_value, pnl_percent

        if quantity <= 0:
            return pnl_value, pnl_percent

        if side == "LONG":
            pnl_value = (current_price - entry_price) * quantity
            pnl_percent = ((current_price - entry_price) / entry_price) * Decimal("100")
        elif side == "SHORT":
            pnl_value = (entry_price - current_price) * quantity
            pnl_percent = ((entry_price - current_price) / entry_price) * Decimal("100")

        return pnl_value, pnl_percent

    @classmethod
    def _compute_progress_to_tp(cls, side, entry_price, current_price, take_profit):
        if take_profit in (None, "") or entry_price <= 0 or current_price <= 0:
            return 0.0

        tp = cls._to_decimal(take_profit, default="0")
        if tp <= 0:
            return 0.0

        progress = Decimal("0")

        try:
            if side == "LONG" and tp > entry_price:
                progress = ((current_price - entry_price) / (tp - entry_price)) * Decimal("100")
            elif side == "SHORT" and tp < entry_price:
                progress = ((entry_price - current_price) / (entry_price - tp)) * Decimal("100")
        except (InvalidOperation, ZeroDivisionError):
            progress = Decimal("0")

        progress = cls._clamp_decimal(progress, Decimal("0"), Decimal("100"))
        return float(progress)

    @classmethod
    def _compute_progress_to_sl(cls, side, entry_price, current_price, stop_loss):
        if stop_loss in (None, "") or entry_price <= 0 or current_price <= 0:
            return 0.0

        sl = cls._to_decimal(stop_loss, default="0")
        if sl <= 0:
            return 0.0

        progress = Decimal("0")

        try:
            if side == "LONG" and sl < entry_price:
                progress = ((entry_price - current_price) / (entry_price - sl)) * Decimal("100")
            elif side == "SHORT" and sl > entry_price:
                progress = ((current_price - entry_price) / (sl - entry_price)) * Decimal("100")
        except (InvalidOperation, ZeroDivisionError):
            progress = Decimal("0")

        progress = cls._clamp_decimal(progress, Decimal("0"), Decimal("100"))
        return float(progress)

    def get(self, request, *args, **kwargs):
        portfolio = _safe_get_default_portfolio(request.user)

        if not portfolio:
            return JsonResponse({
                "portfolio": None,
                "stats": {
                    "balance": 0,
                    "equity": 0,
                    "available_cash": 0,
                    "locked_cash": 0,
                    "realized_pnl": 0,
                    "unrealized_pnl": 0,
                    "total_pnl": 0,
                    "pnl_percent": 0,
                    "open_positions_count": 0,
                    "orders_count": 0,
                    "filled_orders": 0,
                    "submitted_orders": 0,
                    "long_positions_count": 0,
                    "short_positions_count": 0,
                    "winners_count": 0,
                    "losers_count": 0,
                },
                "positions": [],
                "recent_orders": [],
                "server_time": timezone.now().isoformat(),
            })

        open_positions_qs = (
            Position.objects
            .filter(portfolio=portfolio, status__in=["OPEN", "PARTIALLY_CLOSED"])
            .select_related("asset", "broker_account")
            .order_by("-opened_at")
        )

        open_positions = list(open_positions_qs)
        orders_qs = (
            Order.objects
            .filter(portfolio=portfolio)
            .select_related("signal", "asset", "broker_account")
            .order_by("-created_at")
        )
        recent_orders_qs = orders_qs[:12]

        total_unrealized = Decimal("0")
        winners_count = 0
        losers_count = 0
        long_positions_count = 0
        short_positions_count = 0
        positions_payload = []

        for pos in open_positions:
            asset = getattr(pos, "asset", None)
            symbol = getattr(asset, "symbol", "") if asset else (getattr(pos, "symbol", "") or "")
            side = (getattr(pos, "side", "") or "").upper()

            if side == "LONG":
                long_positions_count += 1
            elif side == "SHORT":
                short_positions_count += 1

            entry_price = self._to_decimal(getattr(pos, "entry_price", None), default="0")
            quantity = self._to_decimal(getattr(pos, "quantity", None), default="0")

            chart_rows, chart = ([], [])
            if asset:
                chart_rows, chart = self._get_clean_chart_for_asset(
                    asset=asset,
                    limit=self.DEFAULT_CHART_POINTS,
                )

            live_price = self._get_live_price(pos, chart_rows)

            pnl_value, pnl_percent = self._compute_pnl(
                pos=pos,
                side=side,
                symbol=symbol,
                entry_price=entry_price,
                current_price=live_price,
                quantity=quantity,
            )

            total_unrealized += pnl_value

            if pnl_value > 0:
                winners_count += 1
            elif pnl_value < 0:
                losers_count += 1

            stop_loss = getattr(pos, "stop_loss", None)
            take_profit = getattr(pos, "take_profit", None)

            progress_to_tp = self._compute_progress_to_tp(
                side=side,
                entry_price=entry_price,
                current_price=live_price,
                take_profit=take_profit,
            )

            progress_to_sl = self._compute_progress_to_sl(
                side=side,
                entry_price=entry_price,
                current_price=live_price,
                stop_loss=stop_loss,
            )

            positions_payload.append({
                "id": pos.id,
                "symbol": symbol,
                "asset_name": getattr(asset, "name", "") or symbol,
                "side": side,
                "quantity": self._to_float(quantity),
                "entry_price": self._to_float(entry_price),
                "current_price": self._to_float(live_price),
                "stop_loss": self._to_float(stop_loss) if stop_loss not in (None, "") else None,
                "take_profit": self._to_float(take_profit) if take_profit not in (None, "") else None,
                "pnl_value": self._to_float(pnl_value),
                "pnl_percent": self._to_float(pnl_percent),
                "opened_at": pos.opened_at.isoformat() if getattr(pos, "opened_at", None) else None,
                "progress_to_tp": progress_to_tp,
                "progress_to_sl": progress_to_sl,
                "chart": chart,
                "is_synthetic": self._is_synthetic_symbol(symbol),
            })

        recent_orders = [
            {
                "id": order.id,
                "symbol": getattr(order, "symbol", "") or "",
                "side": getattr(order, "side", "") or "",
                "status": getattr(order, "status", "") or "",
                "order_type": getattr(order, "order_type", "") or "",
                "quantity": self._to_float(
                    getattr(order, "approved_quantity", None)
                    or getattr(order, "requested_quantity", None)
                ),
                "price": self._to_float(
                    getattr(order, "requested_price", None)
                    or getattr(order, "price", None)
                ),
                "created_at": order.created_at.isoformat() if getattr(order, "created_at", None) else None,
            }
            for order in recent_orders_qs
        ]

        balance = self._to_decimal(getattr(portfolio, "current_balance", 0) or 0)
        equity = self._to_decimal(getattr(portfolio, "equity", balance) or balance)
        available_cash = self._to_decimal(getattr(portfolio, "available_cash", 0) or 0)
        locked_cash = self._to_decimal(getattr(portfolio, "locked_cash", 0) or 0)
        realized_pnl = self._to_decimal(getattr(portfolio, "realized_pnl", 0) or 0)
        total_pnl = realized_pnl + total_unrealized

        pnl_percent = Decimal("0")
        if balance > 0:
            try:
                pnl_percent = (total_pnl / balance) * Decimal("100")
            except Exception:
                pnl_percent = Decimal("0")

        return JsonResponse({
            "portfolio": {
                "id": portfolio.id,
                "name": getattr(portfolio, "name", "") or "",
                "broker": (
                    getattr(portfolio.broker_account, "name", "")
                    if getattr(portfolio, "broker_account", None)
                    else ""
                ),
            },
            "stats": {
                "balance": self._to_float(balance),
                "equity": self._to_float(equity),
                "available_cash": self._to_float(available_cash),
                "locked_cash": self._to_float(locked_cash),
                "realized_pnl": self._to_float(realized_pnl),
                "unrealized_pnl": self._to_float(total_unrealized),
                "total_pnl": self._to_float(total_pnl),
                "pnl_percent": self._to_float(pnl_percent),
                "open_positions_count": len(open_positions),
                "orders_count": orders_qs.count(),
                "filled_orders": orders_qs.filter(status="FILLED").count(),
                "submitted_orders": orders_qs.filter(status__in=["SUBMITTED", "PARTIALLY_FILLED"]).count(),
                "long_positions_count": long_positions_count,
                "short_positions_count": short_positions_count,
                "winners_count": winners_count,
                "losers_count": losers_count,
            },
            "positions": positions_payload,
            "recent_orders": recent_orders,
            "server_time": timezone.now().isoformat(),
        })

@login_required
@require_POST
def trading_mode_toggle(request):
    """
    Bascule le mode de trading (PAPER ↔ LIVE) pour l'utilisateur courant.

    Le mode est la PROPRIÉTÉ DU BROKER ACCOUNT (cf. BrokerAdapterFactory) :
    si on ne le persiste qu'en session, le sidebar affiche LIVE mais
    l'orchestrateur continue de router vers PaperBrokerAdapter et rien
    n'arrive chez le broker. C'est exactement ce qui s'est passé pour
    l'ordre #41.

    Stratégie de mise à jour
    ------------------------
    On bascule TOUS les BrokerAccount actifs de l'utilisateur, parce que
    l'interrupteur du sidebar est un choix global ("je veux tester en
    PAPER" vs "je veux trader en LIVE"). La granularité par-compte reste
    accessible via la page Brokers (formulaire d'édition).

    Garde-fous
    ----------
    - On refuse LIVE si aucun BrokerAccount actif n'est configuré.
    - Pour Deriv en LIVE : on vérifie la présence d'un deriv_token. À
      défaut, on bascule quand même mais on prévient explicitement.
    - On loggue chaque transition pour audit (broker_account_mode_toggled).
    """
    import logging
    from brokers.models import BrokerAccount

    log = logging.getLogger("leotrade.dashboard.mode_toggle")

    mode = (request.POST.get("mode") or "").strip().upper()
    if mode not in ("PAPER", "LIVE"):
        mode = "PAPER"

    accounts = list(
        BrokerAccount.objects.filter(user=request.user, is_active=True)
    )

    if not accounts:
        # Pas de broker : on garde la valeur en session pour l'UI mais
        # on prévient l'utilisateur que ça n'aura aucun effet réel tant
        # qu'aucun broker n'est lié.
        request.session["trading_mode"] = mode
        messages.warning(
            request,
            "Aucun broker actif configuré. Le mode est mémorisé pour l'UI "
            "mais aucune exécution ne sera possible tant qu'un broker n'est "
            "pas créé dans la page Brokers."
        )
        return redirect(request.META.get("HTTP_REFERER") or "dashboard")

    flipped = []
    skipped = []
    deriv_no_token = []

    for acc in accounts:
        if acc.mode == mode:
            skipped.append(acc)
            continue

        if mode == "LIVE" and acc.broker == "DERIV" and not getattr(acc, "deriv_token", None):
            deriv_no_token.append(acc)

        old_mode = acc.mode
        acc.mode = mode
        try:
            acc.save(update_fields=["mode", "updated_at"])
        except Exception:
            acc.save(update_fields=["mode"])
        flipped.append(acc)

        log.info(
            "broker_account_mode_toggled user_id=%s broker_account_id=%s "
            "broker=%s old_mode=%s new_mode=%s",
            request.user.id, acc.id, acc.broker, old_mode, mode,
        )

    # Met aussi à jour la session pour que le sidebar affiche immédiatement
    # le nouvel état même avant le prochain rafraîchissement complet.
    request.session["trading_mode"] = mode

    if flipped:
        names = ", ".join(f"#{a.id} {a.broker}/{a.name}" for a in flipped)
        messages.success(
            request,
            f"Mode de trading basculé sur {mode}. Comptes mis à jour : {names}."
        )

    if skipped and not flipped:
        messages.info(
            request,
            f"Tous les comptes étaient déjà en mode {mode}. Aucun changement."
        )

    if deriv_no_token:
        names = ", ".join(f"#{a.id} {a.name}" for a in deriv_no_token)
        messages.warning(
            request,
            "Attention : les comptes Deriv suivants sont en LIVE mais n'ont "
            f"pas de token configuré ({names}). Les ordres échoueront tant "
            "que vous n'aurez pas connecté ces comptes via OAuth."
        )

    return redirect(request.META.get("HTTP_REFERER") or "dashboard")


@login_required
def kyc_dashboard(request):
    profile, _ = KYCProfile.objects.get_or_create(user=request.user)
    return render(request, "dashboard/kyc_dashboard.html", {"kyc": profile})


@login_required
def kyc_submit(request):
    profile, _ = KYCProfile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        form = KYCSubmissionForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.status = "PENDING"
            obj.rejection_reason = ""
            obj.save()
            messages.success(request, "Votre dossier KYC a été soumis.")
            return redirect("kyc-dashboard")
    else:
        form = KYCSubmissionForm(instance=profile)

    return render(request, "dashboard/submit.html", {
        "form": form,
        "kyc": profile,
    })


@staff_member_required
def admin_kyc_list(request):
    status = request.GET.get("status", "").strip()
    q = request.GET.get("q", "").strip()

    profiles = KYCProfile.objects.select_related("user", "reviewed_by").order_by("-updated_at")

    if status:
        profiles = profiles.filter(status=status)

    if q:
        profiles = (
            profiles.filter(user__email__icontains=q)
            | profiles.filter(full_name__icontains=q)
            | profiles.filter(id_document_number__icontains=q)
        )

    paginator = Paginator(profiles, 30)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "dashboard/admin/kyc_list.html", {
        "profiles": page_obj,
        "page_obj": page_obj,
        "status_filter": status,
        "q": q,
    })


@staff_member_required
def admin_kyc_detail(request, pk):
    profile = get_object_or_404(KYCProfile.objects.select_related("user", "reviewed_by"), pk=pk)
    return render(request, "dashboard/admin/kyc_detail.html", {
        "kyc": profile,
    })


@staff_member_required
@require_POST
def admin_kyc_approve(request, pk):
    profile = get_object_or_404(KYCProfile, pk=pk)
    profile.status = "APPROVED"
    profile.reviewed_by = request.user
    profile.reviewed_at = timezone.now()
    profile.admin_note = request.POST.get("admin_note", "")
    profile.rejection_reason = ""
    profile.save(update_fields=[
        "status",
        "reviewed_by",
        "reviewed_at",
        "admin_note",
        "rejection_reason",
        "updated_at",
    ])
    messages.success(request, "Dossier KYC approuvé.")
    return redirect("admin-kyc-detail", pk=profile.pk)


@staff_member_required
@require_POST
def admin_kyc_reject(request, pk):
    profile = get_object_or_404(KYCProfile, pk=pk)
    profile.status = "REJECTED"
    profile.reviewed_by = request.user
    profile.reviewed_at = timezone.now()
    profile.admin_note = request.POST.get("admin_note", "")
    profile.rejection_reason = request.POST.get("rejection_reason", "").strip() or "Dossier rejeté."
    profile.save(update_fields=[
        "status",
        "reviewed_by",
        "reviewed_at",
        "admin_note",
        "rejection_reason",
        "updated_at",
    ])
    messages.success(request, "Dossier KYC rejeté.")
    return redirect("admin-kyc-detail", pk=profile.pk)