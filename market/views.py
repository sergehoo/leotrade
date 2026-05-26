# /Users/ogahserge/Documents/leoTrade/market/views.py
import json
import logging
from decimal import Decimal, InvalidOperation

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db.models import Q, Count, Max, Min
from django.http import JsonResponse
from django.views import View
from django.views.generic import ListView, DetailView, TemplateView

from brokers.models import BrokerAccount
from portfolio.models import Portfolio

from .models import Asset, Candle, Timeframe

logger = logging.getLogger(__name__)


class AssetListView(LoginRequiredMixin, TemplateView):
    template_name = "market/asset_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        search = (self.request.GET.get("q") or "").strip()
        asset_class = (self.request.GET.get("asset_class") or "").strip()
        exchange = (self.request.GET.get("exchange") or "").strip()
        status = (self.request.GET.get("status") or "").strip()
        sort = (self.request.GET.get("sort") or "symbol").strip()

        qs = (
            Asset.objects
            .all()
            .annotate(
                candles_count=Count("candles", distinct=True),
                last_candle_time=Max("candles__open_time"),
                first_candle_time=Min("candles__open_time"),
            )
        )

        if search:
            qs = qs.filter(
                Q(symbol__icontains=search)
                | Q(name__icontains=search)
                | Q(base_asset__icontains=search)
                | Q(quote_asset__icontains=search)
            )

        if asset_class:
            qs = qs.filter(asset_class=asset_class)

        if exchange:
            qs = qs.filter(exchange=exchange)

        if status == "active":
            qs = qs.filter(is_active=True)
        elif status == "inactive":
            qs = qs.filter(is_active=False)

        allowed_sorts = {
            "symbol": "symbol",
            "-symbol": "-symbol",
            "class": "asset_class",
            "-class": "-asset_class",
            "exchange": "exchange",
            "-exchange": "-exchange",
            "candles": "candles_count",
            "-candles": "-candles_count",
            "recent": "-last_candle_time",
            "oldest": "last_candle_time",
        }
        qs = qs.order_by(allowed_sorts.get(sort, "symbol"))

        paginator = Paginator(qs, 20)
        page_obj = paginator.get_page(self.request.GET.get("page"))

        stats_base = Asset.objects.all()
        if search:
            stats_base = stats_base.filter(
                Q(symbol__icontains=search)
                | Q(name__icontains=search)
                | Q(base_asset__icontains=search)
                | Q(quote_asset__icontains=search)
            )
        if asset_class:
            stats_base = stats_base.filter(asset_class=asset_class)
        if exchange:
            stats_base = stats_base.filter(exchange=exchange)
        if status == "active":
            stats_base = stats_base.filter(is_active=True)
        elif status == "inactive":
            stats_base = stats_base.filter(is_active=False)

        total_assets = stats_base.count()
        active_assets = stats_base.filter(is_active=True).count()
        inactive_assets = stats_base.filter(is_active=False).count()
        deriv_assets = stats_base.filter(exchange="DERIV").count()
        binance_assets = stats_base.filter(exchange="BINANCE").count()

        exchanges = (
            Asset.objects.order_by("exchange")
            .values_list("exchange", flat=True)
            .distinct()
        )

        context.update({
            "page_obj": page_obj,
            "assets": page_obj.object_list,
            "asset_class_choices": Asset.ASSET_CLASS_CHOICES,
            "exchanges": exchanges,
            "filters": {
                "q": search,
                "asset_class": asset_class,
                "exchange": exchange,
                "status": status,
                "sort": sort,
            },
            "stats": {
                "total_assets": total_assets,
                "active_assets": active_assets,
                "inactive_assets": inactive_assets,
                "deriv_assets": deriv_assets,
                "binance_assets": binance_assets,
            }
        })
        return context


class CandleListView(LoginRequiredMixin, ListView):
    model = Candle
    template_name = "market/candle_list.html"
    context_object_name = "candles"
    paginate_by = 50

    def get_queryset(self):
        qs = Candle.objects.select_related("asset", "timeframe").order_by("-open_time")

        asset_id = self.request.GET.get("asset")
        timeframe_id = self.request.GET.get("timeframe")

        if asset_id:
            qs = qs.filter(asset_id=asset_id)

        if timeframe_id:
            qs = qs.filter(timeframe_id=timeframe_id)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["assets"] = Asset.objects.order_by("symbol")
        ctx["timeframes"] = Timeframe.objects.order_by("minutes")
        ctx["selected_asset"] = self.request.GET.get("asset", "")
        ctx["selected_timeframe"] = self.request.GET.get("timeframe", "")
        return ctx


class CandleDetailView(LoginRequiredMixin, DetailView):
    model = Asset
    template_name = "market/candle_detail.html"
    context_object_name = "asset"

    DEFAULT_TIMEFRAME = "1m"
    MAX_CANDLES = 300

    def get_selected_timeframe(self):
        timeframe_code = self.request.GET.get("timeframe", self.DEFAULT_TIMEFRAME)
        timeframe = Timeframe.objects.filter(code=timeframe_code).first()

        if timeframe:
            return timeframe

        return Timeframe.objects.order_by("minutes").first()

    def get_candles_queryset(self, asset, timeframe):
        qs = (
            Candle.objects
            .filter(asset=asset)
            .select_related("timeframe")
            .order_by("-open_time")
        )

        if timeframe:
            qs = qs.filter(timeframe=timeframe)

        return qs[:self.MAX_CANDLES]

    def serialize_candle(self, row):
        return {
            "open_time": int(row.open_time.timestamp()) if row.open_time else None,
            "open_time_iso": row.open_time.isoformat() if row.open_time else None,
            "open": float(row.open) if row.open is not None else 0.0,
            "high": float(row.high) if row.high is not None else 0.0,
            "low": float(row.low) if row.low is not None else 0.0,
            "close": float(row.close) if row.close is not None else 0.0,
            "volume": float(row.volume) if row.volume is not None else 0.0,
            "timeframe": row.timeframe.code if row.timeframe_id else "",
        }

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        selected_timeframe = self.get_selected_timeframe()
        candles_desc = list(self.get_candles_queryset(self.object, selected_timeframe))
        candles = list(reversed(candles_desc))

        candles_payload = [self.serialize_candle(c) for c in candles]

        latest_candle = candles[-1] if candles else None
        previous_candle = candles[-2] if len(candles) > 1 else None

        price_change = None
        price_change_percent = None

        if latest_candle and previous_candle and previous_candle.close not in (None, 0):
            price_change = latest_candle.close - previous_candle.close
            price_change_percent = (price_change / previous_candle.close) * Decimal("100")

        ctx["timeframes"] = Timeframe.objects.order_by("minutes")
        ctx["selected_timeframe"] = selected_timeframe
        ctx["candles_json"] = json.dumps(candles_payload)
        ctx["live_feed_url"] = self.request.build_absolute_uri(
            f"/market/assets/{self.object.pk}/candles/live/"
        )
        ctx["latest_candle"] = latest_candle
        ctx["price_change"] = price_change
        ctx["price_change_percent"] = price_change_percent
        ctx["candles_count"] = len(candles)
        scheme = "wss" if self.request.is_secure() else "ws"
        ctx["ws_feed_url"] = f"{scheme}://{self.request.get_host()}/ws/market/candles/{self.object.pk}/{selected_timeframe.code}/"

        return ctx


class CandleLiveFeedView(LoginRequiredMixin, View):
    MAX_CANDLES = 300

    def get(self, request, pk, *args, **kwargs):
        asset = Asset.objects.filter(pk=pk).first()
        if not asset:
            return JsonResponse({"detail": "Actif introuvable."}, status=404)

        timeframe_code = request.GET.get("timeframe")
        timeframe = None

        if timeframe_code:
            timeframe = Timeframe.objects.filter(code=timeframe_code).first()

        qs = (
            Candle.objects
            .filter(asset=asset)
            .select_related("timeframe")
            .order_by("-open_time")
        )

        if timeframe:
            qs = qs.filter(timeframe=timeframe)

        candles = list(reversed(list(qs[:self.MAX_CANDLES])))

        payload = []
        for c in candles:
            payload.append({
                "open_time": int(c.open_time.timestamp()) if c.open_time else None,
                "open_time_iso": c.open_time.isoformat() if c.open_time else None,
                "open": float(c.open) if c.open is not None else 0.0,
                "high": float(c.high) if c.high is not None else 0.0,
                "low": float(c.low) if c.low is not None else 0.0,
                "close": float(c.close) if c.close is not None else 0.0,
                "volume": float(c.volume) if c.volume is not None else 0.0,
                "timeframe": c.timeframe.code if c.timeframe_id else "",
            })

        latest = payload[-1] if payload else None
        previous = payload[-2] if len(payload) > 1 else None

        change = 0
        change_percent = 0

        if latest and previous and previous["close"] not in (None, 0):
            change = latest["close"] - previous["close"]
            change_percent = (change / previous["close"]) * 100

        return JsonResponse({
            "asset": {
                "id": asset.id,
                "symbol": asset.symbol,
                "asset_class": asset.asset_class,
                "exchange": asset.exchange,
                "is_active": asset.is_active,
            },
            "timeframe": timeframe.code if timeframe else "",
            "count": len(payload),
            "latest": latest,
            "change": change,
            "change_percent": change_percent,
            "candles": payload,
        })


# =============================================================================
# Vue détail d'un actif (page principale + panneau trade)
# =============================================================================

class AssetDetailView(LoginRequiredMixin, DetailView):
    """
    Page détail d'un actif : méta-données, dernier prix, et panneau de
    passage d'ordre rapide (BUY / SELL) directement depuis la fiche actif.
    """
    model = Asset
    template_name = "market/asset_detail.html"
    context_object_name = "asset"

    MAX_CANDLES = 10

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        asset = self.object

        # Dernier timeframe disponible
        timeframes = Timeframe.objects.order_by("minutes")
        selected_tf_code = self.request.GET.get("timeframe", "")
        selected_tf = (
            timeframes.filter(code=selected_tf_code).first()
            if selected_tf_code
            else timeframes.first()
        )

        # Dernières bougies pour affichage rapide
        candles_qs = (
            Candle.objects
            .filter(asset=asset)
            .select_related("timeframe")
            .order_by("-open_time")
        )
        if selected_tf:
            candles_qs = candles_qs.filter(timeframe=selected_tf)

        recent_candles = list(reversed(list(candles_qs[:self.MAX_CANDLES])))

        latest = recent_candles[-1] if recent_candles else None
        previous = recent_candles[-2] if len(recent_candles) > 1 else None

        price_change = price_change_pct = None
        if latest and previous and previous.close and previous.close != 0:
            price_change = latest.close - previous.close
            price_change_pct = (price_change / previous.close) * Decimal("100")

        # Brokers et portfolios de l'utilisateur pour le panneau trade
        brokers = (
            BrokerAccount.objects
            .filter(user=self.request.user, is_active=True)
            .order_by("broker", "mode")
        )
        portfolios = (
            Portfolio.objects
            .filter(user=self.request.user, is_active=True)
            .select_related("broker_account")
            .order_by("name")
        )

        # Timeframes disponibles pour cet actif
        # related_name sur Timeframe → Candle est "candle" (singulier)
        asset_timeframes = (
            Timeframe.objects
            .filter(candle__asset=asset)
            .distinct()
            .order_by("minutes")
        )

        ctx.update({
            "timeframes": timeframes,
            "asset_timeframes": asset_timeframes,
            "selected_timeframe": selected_tf,
            "recent_candles": recent_candles,
            "latest_candle": latest,
            "previous_candle": previous,
            "price_change": price_change,
            "price_change_pct": price_change_pct,
            "brokers": brokers,
            "portfolios": portfolios,
            "live_feed_url": self.request.build_absolute_uri(
                f"/market/assets/{asset.pk}/candles/live/"
            ),
        })
        return ctx


# =============================================================================
# Endpoint de passage d'ordre rapide depuis la fiche actif
# =============================================================================

class AssetQuickTradeView(LoginRequiredMixin, View):
    """
    POST /market/assets/<pk>/trade/

    Paramètres POST :
        broker_account  — ID du BrokerAccount
        portfolio       — ID du Portfolio
        side            — BUY | SELL
        amount          — mise en USD (Decimal)
        duration        — entier (défaut 5)
        duration_unit   — s | m | h | d (défaut m)

    Retourne JSON :  { ok, order_id, contract_id, error }
    """

    def post(self, request, pk, *args, **kwargs):
        asset = Asset.objects.filter(pk=pk, is_active=True).first()
        if not asset:
            return JsonResponse({"ok": False, "error": "Actif introuvable ou inactif."}, status=404)

        # ── Lecture et validation des paramètres ──────────────────────────
        broker_id = request.POST.get("broker_account", "").strip()
        portfolio_id = request.POST.get("portfolio", "").strip()
        side = request.POST.get("side", "BUY").strip().upper()
        amount_raw = request.POST.get("amount", "").strip()
        duration_raw = request.POST.get("duration", "5").strip()
        duration_unit = request.POST.get("duration_unit", "m").strip().lower()

        errors = []
        if not broker_id:
            errors.append("Broker requis.")
        if not portfolio_id:
            errors.append("Portefeuille requis.")
        if side not in ("BUY", "SELL"):
            errors.append("Sens invalide (BUY ou SELL).")
        if not amount_raw:
            errors.append("Montant requis.")

        try:
            amount = Decimal(amount_raw)
            if amount <= 0:
                errors.append("Le montant doit être supérieur à zéro.")
        except (InvalidOperation, ValueError, TypeError):
            errors.append("Montant invalide.")
            amount = Decimal("0")

        try:
            duration = int(duration_raw)
            if duration <= 0:
                duration = 5
        except (ValueError, TypeError):
            duration = 5

        if duration_unit not in ("s", "m", "h", "d", "t"):
            duration_unit = "m"

        if errors:
            return JsonResponse({"ok": False, "error": " ".join(errors)}, status=400)

        # ── Récupération des objets sécurisés ─────────────────────────────
        broker = BrokerAccount.objects.filter(
            pk=broker_id, user=request.user, is_active=True,
        ).first()
        if not broker:
            return JsonResponse({"ok": False, "error": "Broker introuvable."}, status=404)

        portfolio = Portfolio.objects.filter(
            pk=portfolio_id, user=request.user, is_active=True,
        ).first()
        if not portfolio:
            return JsonResponse({"ok": False, "error": "Portefeuille introuvable."}, status=404)

        # ── Création du signal synthétique et exécution ───────────────────
        try:
            from django.utils import timezone
            from django.utils.text import slugify
            from strategies.models import Strategy, Signal
            from portfolio.services import PortfolioService

            # Recompute avant exécution pour avoir le cash exact
            portfolio = PortfolioService.recompute_cash_state(portfolio)

            # Timeframe minimal pour le signal
            timeframe = Timeframe.objects.order_by("minutes").first()

            # Stratégie synthétique liée à cet asset + broker
            strategy, _ = Strategy.objects.get_or_create(
                slug=slugify(f"quick-trade-{asset.symbol}-{broker.broker}-{broker.mode}"),
                defaults={
                    "name": f"Quick Trade {asset.symbol} ({broker.broker}/{broker.mode})",
                    "strategy_type": "RULE",
                    "asset": asset,
                    "timeframe": timeframe,
                    "status": "PAPER" if broker.mode in ("PAPER", "DEMO") else "LIVE",
                    "is_active": True,
                    "is_autonomous": False,
                    "allow_live_execution": broker.mode == "LIVE",
                    "min_confidence_threshold": 0.1,
                    "parameters": {
                        "deriv_duration": duration,
                        "deriv_duration_unit": duration_unit,
                    },
                },
            )

            signal = Signal.objects.create(
                strategy=strategy,
                candle_time=timezone.now(),
                side=side,
                confidence=0.99,
                price=Decimal("0"),
                status="APPROVED",
                reason=f"Quick trade depuis fiche actif — {asset.symbol} {side}",
            )

            # ── Exécution via ExecutionOrchestrator (chemin unifié) ──────
            # Le Quick Trade direct (depuis la fiche actif) suit désormais
            # exactement le MÊME workflow que les trades IA :
            #
            #   RiskGuardService → ExecutionOrchestrator.create_order()
            #     → ExecutionOrchestrator.submit_order()
            #     → BrokerAdapter (LiveDeriv / LiveBinance / LiveMT5)
            #     → broker response
            #     → FillProcessingService.register_fill()
            #     → Position portfolio mise à jour
            #
            # On ne passe plus par DerivExecutor en direct : la sync
            # broker → portfolio est unifiée et le ledger reste cohérent.
            from execution.services import ExecutionOrchestrator

            # Pour Deriv : 1 contrat = 1 unité (cf. _build_deriv_sizing) ;
            # pour les autres brokers, en quick trade on utilise stake = qty
            # car il n'y a ni stop-loss ni entry_price connu.
            if broker.broker == "DERIV":
                approved_quantity = Decimal("1")
            else:
                approved_quantity = amount

            order = ExecutionOrchestrator.create_order(
                user=request.user,
                portfolio=portfolio,
                broker_account=broker,
                symbol=asset.symbol,
                side=side,
                approved_quantity=approved_quantity,
                requested_stake_amount=amount,
                approved_notional=amount,
                requested_price=Decimal("0"),
                signal=signal,
                trade_idea=None,
                asset=asset,
                order_type="MARKET",
                source="AI_ASSISTED",              # valeur dans SOURCE_CHOICES
                stop_loss=None,
                take_profit=None,
                leverage=Decimal("1"),
                metadata={
                    "source": "asset_quick_trade",
                    "asset_id": asset.id,
                    "duration": duration,
                    "duration_unit": duration_unit,
                },
            )

            # Soumission broker → fills → position. Toute exception remonte
            # ici, marque l'ordre FAILED et libère le cash automatiquement
            # via le rollback intégré à submit_order().
            ExecutionOrchestrator.submit_order(order)
            order.refresh_from_db()

            # Si Deriv : on essaie de remonter l'éventuel contract_id pour
            # que le front affiche tout de suite l'identifiant du contrat.
            contract_id = None
            if broker.broker == "DERIV":
                try:
                    from brokers.models_external_ref import BrokerExternalRef
                    ref = BrokerExternalRef.objects.filter(
                        broker="DERIV",
                        internal_kind="ORDER",
                        internal_id=str(order.id),
                        kind="CONTRACT",
                    ).first()
                    if ref:
                        contract_id = ref.external_id
                except Exception:
                    contract_id = None

            # Message vérité-terrain : on précise PAPER vs LIVE pour que
            # le front comprenne immédiatement si l'ordre est arrivé chez
            # le broker ou s'il est resté en simulation locale.
            broker_order_id = getattr(order, "broker_order_id", None) or "—"
            if broker.mode == "PAPER":
                msg = (
                    f"Ordre #{order.id} simulé en mode PAPER "
                    f"(broker_order_id={broker_order_id}). "
                    f"Aucun ordre n'a été envoyé à {broker.broker}."
                )
            else:
                msg = (
                    f"Ordre #{order.id} envoyé à {broker.broker} en LIVE "
                    f"(broker_order_id={broker_order_id}, statut={order.status})."
                )
            return JsonResponse({
                "ok": True,
                "order_id": order.id,
                "contract_id": contract_id,
                "symbol": asset.symbol,
                "status": order.status,
                "broker": broker.broker,
                "broker_mode": broker.mode,
                "broker_order_id": broker_order_id,
                "message": msg,
            })

        except Exception as exc:
            logger.exception(
                "asset_quick_trade.failed asset_id=%s broker_id=%s user_id=%s err=%s",
                asset.id, broker.id, request.user.id, exc,
            )
            return JsonResponse({"ok": False, "error": str(exc)}, status=500)
