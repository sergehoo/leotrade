from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import DatabaseError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView

from brokers.models import BrokerAccount
from market.models import Candle
from portfolio.models import Portfolio
from trading.mixins import UserScopedTradeIdeaMixin
from trading.models import TradeIdea, AgentRun
from trading.services.agents.portfolio_advisor_agent import PortfolioAdvisorAgent
from trading.services.trade_idea_execution import TradeIdeaExecutionService, logger
from trading.services.trade_idea_preview import TradeIdeaPreviewService


class TradeIdeaFilterMixin:
    def get_filtered_queryset(self):
        qs = (
            TradeIdea.objects
            .select_related("asset", "timeframe", "strategy", "signal", "scan_run")
            .prefetch_related()
            .filter(user=self.request.user)
            .order_by("-overall_score", "-created_at")
        )

        status_filter = self.request.GET.get("status", "").strip()
        if status_filter:
            qs = qs.filter(status=status_filter)

        symbol_filter = self.request.GET.get("symbol", "").strip()
        if symbol_filter:
            qs = qs.filter(symbol__icontains=symbol_filter)

        direction_filter = self.request.GET.get("direction", "").strip()
        if direction_filter:
            qs = qs.filter(direction=direction_filter)

        return qs


class TradeIdeaListView(LoginRequiredMixin, TradeIdeaFilterMixin, ListView):
    model = TradeIdea
    template_name = "trading/trade_idea_list.html"
    context_object_name = "ideas"
    paginate_by = 30

    def get_queryset(self):
        return self.get_filtered_queryset()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_filter"] = self.request.GET.get("status", "")
        context["symbol_filter"] = self.request.GET.get("symbol", "")
        context["direction_filter"] = self.request.GET.get("direction", "")
        context["live_feed_url"] = reverse("trading:trade-idea-live-feed")
        return context


# class TradeIdeaDetailView(LoginRequiredMixin, UserScopedTradeIdeaMixin, DetailView):
#     model = TradeIdea
#     template_name = "trading/trade_idea_detail.html"
#     context_object_name = "idea"
#
#     def _safe_float(self, value, default=None):
#         try:
#             if value is None or value == "":
#                 return default
#             return float(value)
#         except (TypeError, ValueError, InvalidOperation):
#             return default
#
#     def _compute_market_snapshot(self, idea):
#         asset = getattr(idea, "asset", None)
#         timeframe = getattr(idea, "timeframe", None)
#
#         if not asset:
#             return {}
#
#         qs = Candle.objects.filter(asset=asset).order_by("-open_time")
#         if timeframe:
#             qs = qs.filter(timeframe=timeframe)
#
#         candles = list(reversed(list(qs[:80])))
#
#         if not candles:
#             return {
#                 "has_market_data": False,
#                 "ai_decision": "WATCH",
#                 "ai_reason": "Aucune donnée de marché récente disponible pour confirmer ce setup.",
#             }
#
#         latest = candles[-1]
#         previous = candles[-2] if len(candles) > 1 else None
#
#         last_price = self._safe_decimal(latest.close)
#         previous_close = self._safe_decimal(previous.close) if previous else None
#
#         price_change = None
#         price_change_pct = None
#
#         if last_price is not None and previous_close not in (None, Decimal("0")):
#             price_change = last_price - previous_close
#             price_change_pct = (price_change / previous_close) * Decimal("100")
#
#         closes = [self._safe_decimal(c.close) for c in candles if self._safe_decimal(c.close) is not None]
#         highs = [self._safe_decimal(c.high) for c in candles if self._safe_decimal(c.high) is not None]
#         lows = [self._safe_decimal(c.low) for c in candles if self._safe_decimal(c.low) is not None]
#
#         trend_direction = "UNKNOWN"
#         market_regime = "UNKNOWN"
#         volatility_level = "UNKNOWN"
#         rsi = None
#         atr = None
#         ema_signal = "NEUTRAL"
#
#         if len(closes) >= 20:
#             short_avg = sum(closes[-5:]) / Decimal("5")
#             long_avg = sum(closes[-20:]) / Decimal("20")
#
#             if short_avg > long_avg:
#                 trend_direction = "BULLISH"
#             elif short_avg < long_avg:
#                 trend_direction = "BEARISH"
#
#             ema_signal = "BUY" if short_avg > long_avg else "SELL" if short_avg < long_avg else "NEUTRAL"
#
#         if len(closes) >= 15:
#             gains = []
#             losses = []
#
#             for i in range(-14, 0):
#                 diff = closes[i] - closes[i - 1]
#                 if diff >= 0:
#                     gains.append(diff)
#                     losses.append(Decimal("0"))
#                 else:
#                     gains.append(Decimal("0"))
#                     losses.append(abs(diff))
#
#             avg_gain = sum(gains) / Decimal("14")
#             avg_loss = sum(losses) / Decimal("14")
#
#             if avg_loss == 0:
#                 rsi = Decimal("100")
#             else:
#                 rs = avg_gain / avg_loss
#                 rsi = Decimal("100") - (Decimal("100") / (Decimal("1") + rs))
#
#         if len(highs) >= 14 and len(lows) >= 14 and len(closes) >= 15:
#             trs = []
#             for i in range(-14, 0):
#                 high = highs[i]
#                 low = lows[i]
#                 prev_close = closes[i - 1]
#                 tr = max(
#                     high - low,
#                     abs(high - prev_close),
#                     abs(low - prev_close),
#                 )
#                 trs.append(tr)
#
#             atr = sum(trs) / Decimal("14")
#
#             if last_price and last_price != 0:
#                 atr_pct = (atr / last_price) * Decimal("100")
#                 if atr_pct >= Decimal("2"):
#                     volatility_level = "HIGH"
#                 elif atr_pct >= Decimal("0.7"):
#                     volatility_level = "MEDIUM"
#                 else:
#                     volatility_level = "LOW"
#
#                 market_regime = "TRENDING" if atr_pct >= Decimal("0.7") and trend_direction != "UNKNOWN" else "RANGING"
#
#         ai_decision = "WATCH"
#         ai_reason_parts = []
#
#         direction = str(getattr(idea, "direction", "") or "").upper()
#         confidence = self._safe_decimal(getattr(idea, "confidence_score", None)) or Decimal("0")
#         overall = self._safe_decimal(getattr(idea, "overall_score", None)) or Decimal("0")
#
#         direction_aligned = (
#                                     direction in ("BUY", "CALL") and trend_direction == "BULLISH"
#                             ) or (
#                                     direction in ("SELL", "PUT") and trend_direction == "BEARISH"
#                             )
#
#         if overall >= Decimal("0.75") and confidence >= Decimal("0.70") and direction_aligned:
#             ai_decision = "EXECUTE"
#             ai_reason_parts.append("Le score global, la confiance et la tendance sont alignés.")
#         elif overall >= Decimal("0.60") and direction_aligned:
#             ai_decision = "PLAN"
#             ai_reason_parts.append("Le setup est intéressant mais nécessite validation du risque.")
#         elif overall >= Decimal("0.45"):
#             ai_decision = "WATCH"
#             ai_reason_parts.append("Le signal mérite surveillance, mais la confirmation marché reste moyenne.")
#         else:
#             ai_decision = "REJECT"
#             ai_reason_parts.append("Le score ou l’alignement marché est insuffisant.")
#
#         if rsi is not None:
#             if rsi >= Decimal("70"):
#                 ai_reason_parts.append("RSI élevé : risque de surachat.")
#             elif rsi <= Decimal("30"):
#                 ai_reason_parts.append("RSI faible : risque de survente.")
#
#         if volatility_level == "HIGH":
#             ai_reason_parts.append("Volatilité élevée : réduire la taille de position.")
#
#         return {
#             "has_market_data": True,
#             "last_price": last_price,
#             "price_change": price_change,
#             "price_change_pct": price_change_pct,
#             "trend_direction": trend_direction,
#             "market_regime": market_regime,
#             "volatility_level": volatility_level,
#             "rsi": rsi,
#             "atr": atr,
#             "ema_signal": ema_signal,
#             "ai_decision": ai_decision,
#             "ai_reason": " ".join(ai_reason_parts),
#             "recent_candles": candles[-30:],
#         }
#
#     def get_queryset(self):
#         return (
#             TradeIdea.objects
#             .select_related(
#                 "asset",
#                 "timeframe",
#                 "strategy",
#                 "signal",
#                 "scan_run",
#                 "user",
#             )
#             .filter(user=self.request.user)
#             .order_by("-created_at")
#         )
#
#     def _safe_decimal(self, value):
#         if value is None or value == "":
#             return None
#         try:
#             return Decimal(str(value))
#         except (InvalidOperation, TypeError, ValueError):
#             return None
#
#     def _compute_trade_metrics(self, idea):
#         entry = self._safe_decimal(idea.entry_price)
#         stop = self._safe_decimal(idea.stop_loss)
#         take = self._safe_decimal(idea.take_profit)
#
#         risk_distance = None
#         reward_distance = None
#         risk_percent = None
#         reward_percent = None
#
#         if entry and stop:
#             risk_distance = abs(entry - stop)
#             if entry != 0:
#                 risk_percent = (risk_distance / entry) * Decimal("100")
#
#         if entry and take:
#             reward_distance = abs(take - entry)
#             if entry != 0:
#                 reward_percent = (reward_distance / entry) * Decimal("100")
#
#         return {
#             "entry": entry,
#             "stop": stop,
#             "take": take,
#             "risk_distance": risk_distance,
#             "reward_distance": reward_distance,
#             "risk_percent": risk_percent,
#             "reward_percent": reward_percent,
#         }
#
#     def _status_tone(self, status):
#         mapping = {
#             "NEW": "sky",
#             "REVIEW": "amber",
#             "APPROVED": "emerald",
#             "REJECTED": "red",
#             "EXECUTED": "violet",
#             "EXPIRED": "amber",
#             "CANCELLED": "zinc",
#         }
#         return mapping.get(status, "zinc")
#
#     def _build_broker_suggestions(self, idea, brokers):
#         suggestions = []
#
#         for broker in brokers:
#             preview = TradeIdeaPreviewService.estimate_minimum_stake(
#                 idea=idea,
#                 broker_account=broker,
#             )
#
#             if not isinstance(preview, dict):
#                 preview = {}
#
#             broker_minimum_stake = self._safe_decimal(preview.get("broker_minimum_stake"))
#             risk_minimum_required = self._safe_decimal(preview.get("risk_minimum_required"))
#             suggested_minimum_stake = self._safe_decimal(preview.get("suggested_minimum_stake"))
#             min_qty = self._safe_decimal(preview.get("min_qty"))
#             qty_step = self._safe_decimal(preview.get("qty_step"))
#             min_notional = self._safe_decimal(preview.get("min_notional"))
#
#             suggestions.append({
#                 "broker": broker,
#                 "preview": preview,
#                 "broker_minimum_stake": broker_minimum_stake,
#                 "risk_minimum_required": risk_minimum_required,
#                 "suggested_minimum_stake": suggested_minimum_stake,
#                 "min_qty": min_qty,
#                 "qty_step": qty_step,
#                 "min_notional": min_notional,
#                 "is_available": bool(preview.get("ok")),
#             })
#
#         return suggestions
#
#     def get_context_data(self, **kwargs):
#         ctx = super().get_context_data(**kwargs)
#         idea = self.object
#
#         # Une seule requête broker — triée broker/mode pour les suggestions
#         # (broker_accounts retiré : doublon inutilisé dans le template)
#         brokers = (
#             BrokerAccount.objects
#             .filter(user=self.request.user, is_active=True)
#             .order_by("broker", "mode", "id")
#         )
#
#         portfolios = (
#             Portfolio.objects
#             .filter(user=self.request.user, is_active=True)
#             .select_related("broker_account")
#             .order_by("name")
#         )
#
#         # ── Détection des kill switches actifs sur les portefeuilles
#         # affichés dans le formulaire d'exécution. Permet d'afficher un
#         # bandeau actionnable (« Résoudre le kill switch ») au-dessus
#         # du formulaire au lieu de laisser l'erreur arriver après le clic.
#         try:
#             from risk.services import RiskGuardService
#             portfolios_with_kill_switch = [
#                 p for p in portfolios
#                 if RiskGuardService.has_active_kill_switch(p)
#             ]
#         except Exception:
#             portfolios_with_kill_switch = []
#
#         broker_suggestions = self._build_broker_suggestions(idea, brokers)
#
#         suggested_minimum_amount = None
#         if broker_suggestions:
#             valid_amounts = [
#                 item["suggested_minimum_stake"]
#                 for item in broker_suggestions
#                 if item["suggested_minimum_stake"] is not None and item["suggested_minimum_stake"] > 0
#             ]
#             if valid_amounts:
#                 suggested_minimum_amount = min(valid_amounts)
#
#         feedback = getattr(idea, "feedback", None)
#
#         latest_agent_run = None
#         if idea.scan_run_id:
#             latest_agent_run = (
#                 AgentRun.objects
#                 .filter(
#                     market_scan_run=idea.scan_run,
#                     user=self.request.user,
#                 )
#                 .order_by("-created_at")
#                 .first()
#             )
#
#         metrics = self._compute_trade_metrics(idea)
#
#         now = timezone.now()
#         expires_in_seconds = None
#         expires_in_minutes = None
#         if idea.expires_at:
#             delta = idea.expires_at - now
#             expires_in_seconds = int(delta.total_seconds())
#             expires_in_minutes = int(delta.total_seconds() // 60)
#         market_snapshot = self._compute_market_snapshot(idea)
#         ctx.update({
#             "market_snapshot": market_snapshot,
#             "ai_decision": market_snapshot.get("ai_decision", "WATCH"),
#             "ai_reason": market_snapshot.get("ai_reason", ""),
#             "recent_market_candles": market_snapshot.get("recent_candles", []),
#             "brokers": brokers,
#             "broker_suggestions": broker_suggestions,
#             "suggested_minimum_amount": suggested_minimum_amount,
#             "portfolios": portfolios,
#             "portfolios_with_kill_switch": portfolios_with_kill_switch,
#             "feedback": feedback,
#             "latest_agent_run": latest_agent_run,
#             "trade_metrics": metrics,
#             "is_expired": idea.is_expired,
#             "expires_in_seconds": expires_in_seconds,
#             "expires_in_minutes": expires_in_minutes,
#             "status_tone": self._status_tone(idea.status),
#         })
#         return ctx
class TradeIdeaDetailView(LoginRequiredMixin, UserScopedTradeIdeaMixin, DetailView):
    model = TradeIdea
    template_name = "trading/trade_idea_detail.html"
    context_object_name = "idea"

    DERIV_MULTIPLIER_PREFIXES = ("BOOM", "CRASH")

    def _safe_decimal(self, value):
        if value is None or value == "":
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None

    def _safe_float(self, value, default=None):
        try:
            if value is None or value == "":
                return default
            return float(value)
        except (TypeError, ValueError, InvalidOperation):
            return default

    def _is_deriv_multiplier_symbol(self, symbol: str) -> bool:
        symbol = str(symbol or "").upper().strip()
        return symbol.startswith(self.DERIV_MULTIPLIER_PREFIXES)

    def _status_tone(self, status):
        mapping = {
            "NEW": "sky",
            "REVIEW": "amber",
            "APPROVED": "emerald",
            "REJECTED": "red",
            "EXECUTED": "violet",
            "ORDER_SUBMITTED": "sky",
            "SUBMITTED": "sky",
            "PENDING": "amber",
            "FILLED": "emerald",
            "PARTIALLY_FILLED": "amber",
            "FAILED": "red",
            "EXPIRED": "amber",
            "CANCELLED": "zinc",
        }
        return mapping.get(str(status or "").upper(), "zinc")

    def _compute_trade_metrics(self, idea):
        entry = self._safe_decimal(idea.entry_price)
        stop = self._safe_decimal(idea.stop_loss)
        take = self._safe_decimal(idea.take_profit)

        risk_distance = None
        reward_distance = None
        risk_percent = None
        reward_percent = None

        if entry and stop:
            risk_distance = abs(entry - stop)
            if entry != 0:
                risk_percent = (risk_distance / entry) * Decimal("100")

        if entry and take:
            reward_distance = abs(take - entry)
            if entry != 0:
                reward_percent = (reward_distance / entry) * Decimal("100")

        return {
            "entry": entry,
            "stop": stop,
            "take": take,
            "risk_distance": risk_distance,
            "reward_distance": reward_distance,
            "risk_percent": risk_percent,
            "reward_percent": reward_percent,
        }

    def _compute_market_snapshot(self, idea):
        asset = getattr(idea, "asset", None)
        timeframe = getattr(idea, "timeframe", None)

        if not asset:
            return {}

        qs = Candle.objects.filter(asset=asset).order_by("-open_time")
        if timeframe:
            qs = qs.filter(timeframe=timeframe)

        candles = list(reversed(list(qs[:80])))

        if not candles:
            return {
                "has_market_data": False,
                "ai_decision": "WATCH",
                "ai_reason": "Aucune donnée de marché récente disponible pour confirmer ce setup.",
            }

        latest = candles[-1]
        previous = candles[-2] if len(candles) > 1 else None

        last_price = self._safe_decimal(latest.close)
        previous_close = self._safe_decimal(previous.close) if previous else None

        price_change = None
        price_change_pct = None

        if last_price is not None and previous_close not in (None, Decimal("0")):
            price_change = last_price - previous_close
            price_change_pct = (price_change / previous_close) * Decimal("100")

        closes = [self._safe_decimal(c.close) for c in candles if self._safe_decimal(c.close) is not None]
        highs = [self._safe_decimal(c.high) for c in candles if self._safe_decimal(c.high) is not None]
        lows = [self._safe_decimal(c.low) for c in candles if self._safe_decimal(c.low) is not None]

        trend_direction = "UNKNOWN"
        market_regime = "UNKNOWN"
        volatility_level = "UNKNOWN"
        rsi = None
        atr = None
        ema_signal = "NEUTRAL"

        if len(closes) >= 20:
            short_avg = sum(closes[-5:]) / Decimal("5")
            long_avg = sum(closes[-20:]) / Decimal("20")

            if short_avg > long_avg:
                trend_direction = "BULLISH"
            elif short_avg < long_avg:
                trend_direction = "BEARISH"

            ema_signal = "BUY" if short_avg > long_avg else "SELL" if short_avg < long_avg else "NEUTRAL"

        if len(closes) >= 15:
            gains = []
            losses = []

            for i in range(-14, 0):
                diff = closes[i] - closes[i - 1]
                if diff >= 0:
                    gains.append(diff)
                    losses.append(Decimal("0"))
                else:
                    gains.append(Decimal("0"))
                    losses.append(abs(diff))

            avg_gain = sum(gains) / Decimal("14")
            avg_loss = sum(losses) / Decimal("14")

            if avg_loss == 0:
                rsi = Decimal("100")
            else:
                rs = avg_gain / avg_loss
                rsi = Decimal("100") - (Decimal("100") / (Decimal("1") + rs))

        if len(highs) >= 14 and len(lows) >= 14 and len(closes) >= 15:
            trs = []

            for i in range(-14, 0):
                high = highs[i]
                low = lows[i]
                prev_close = closes[i - 1]
                tr = max(
                    high - low,
                    abs(high - prev_close),
                    abs(low - prev_close),
                )
                trs.append(tr)

            atr = sum(trs) / Decimal("14")

            if last_price and last_price != 0:
                atr_pct = (atr / last_price) * Decimal("100")
                if atr_pct >= Decimal("2"):
                    volatility_level = "HIGH"
                elif atr_pct >= Decimal("0.7"):
                    volatility_level = "MEDIUM"
                else:
                    volatility_level = "LOW"

                market_regime = (
                    "TRENDING"
                    if atr_pct >= Decimal("0.7") and trend_direction != "UNKNOWN"
                    else "RANGING"
                )

        ai_decision = "WATCH"
        ai_reason_parts = []

        direction = str(getattr(idea, "direction", "") or "").upper()
        confidence = self._safe_decimal(getattr(idea, "confidence_score", None)) or Decimal("0")
        overall = self._safe_decimal(getattr(idea, "overall_score", None)) or Decimal("0")

        direction_aligned = (
            direction in ("BUY", "CALL") and trend_direction == "BULLISH"
        ) or (
            direction in ("SELL", "PUT") and trend_direction == "BEARISH"
        )

        if overall >= Decimal("0.75") and confidence >= Decimal("0.70") and direction_aligned:
            ai_decision = "EXECUTE"
            ai_reason_parts.append("Le score global, la confiance et la tendance sont alignés.")
        elif overall >= Decimal("0.60") and direction_aligned:
            ai_decision = "PLAN"
            ai_reason_parts.append("Le setup est intéressant mais nécessite validation du risque.")
        elif overall >= Decimal("0.45"):
            ai_decision = "WATCH"
            ai_reason_parts.append("Le signal mérite surveillance, mais la confirmation marché reste moyenne.")
        else:
            ai_decision = "REJECT"
            ai_reason_parts.append("Le score ou l’alignement marché est insuffisant.")

        if rsi is not None:
            if rsi >= Decimal("70"):
                ai_reason_parts.append("RSI élevé : risque de surachat.")
            elif rsi <= Decimal("30"):
                ai_reason_parts.append("RSI faible : risque de survente.")

        if volatility_level == "HIGH":
            ai_reason_parts.append("Volatilité élevée : réduire la taille de position.")

        return {
            "has_market_data": True,
            "last_price": last_price,
            "price_change": price_change,
            "price_change_pct": price_change_pct,
            "trend_direction": trend_direction,
            "market_regime": market_regime,
            "volatility_level": volatility_level,
            "rsi": rsi,
            "atr": atr,
            "ema_signal": ema_signal,
            "ai_decision": ai_decision,
            "ai_reason": " ".join(ai_reason_parts),
            "recent_candles": candles[-30:],
        }

    def get_queryset(self):
        return (
            TradeIdea.objects
            .select_related(
                "asset",
                "timeframe",
                "strategy",
                "signal",
                "scan_run",
                "user",
            )
            .filter(user=self.request.user)
            .order_by("-created_at")
        )

    def _build_broker_suggestions(self, idea, brokers):
        suggestions = []

        for broker in brokers:
            preview = TradeIdeaPreviewService.estimate_minimum_stake(
                idea=idea,
                broker_account=broker,
            )

            if not isinstance(preview, dict):
                preview = {}

            broker_minimum_stake = self._safe_decimal(preview.get("broker_minimum_stake"))
            risk_minimum_required = self._safe_decimal(preview.get("risk_minimum_required"))
            suggested_minimum_stake = self._safe_decimal(preview.get("suggested_minimum_stake"))
            min_qty = self._safe_decimal(preview.get("min_qty"))
            qty_step = self._safe_decimal(preview.get("qty_step"))
            min_notional = self._safe_decimal(preview.get("min_notional"))

            broker_name = str(getattr(broker, "broker", "") or "").upper()
            is_deriv = broker_name == "DERIV"
            is_deriv_multiplier = is_deriv and self._is_deriv_multiplier_symbol(idea.symbol)

            suggestions.append({
                "broker": broker,
                "preview": preview,
                "broker_minimum_stake": broker_minimum_stake,
                "risk_minimum_required": risk_minimum_required,
                "suggested_minimum_stake": suggested_minimum_stake,
                "min_qty": min_qty,
                "qty_step": qty_step,
                "min_notional": min_notional,
                "is_available": bool(preview.get("ok")),
                "is_deriv": is_deriv,
                "is_deriv_multiplier": is_deriv_multiplier,
                "deriv_contract_hint": (
                    "Boom/Crash utilise MULTUP/MULTDOWN avec multiplier, sans durée."
                    if is_deriv_multiplier else ""
                ),
            })

        return suggestions

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        idea = self.object

        brokers = (
            BrokerAccount.objects
            .filter(user=self.request.user, is_active=True)
            .order_by("broker", "mode", "id")
        )

        portfolios = (
            Portfolio.objects
            .filter(user=self.request.user, is_active=True)
            .select_related("broker_account")
            .order_by("name")
        )

        try:
            from risk.services import RiskGuardService
            portfolios_with_kill_switch = [
                p for p in portfolios
                if RiskGuardService.has_active_kill_switch(p)
            ]
        except Exception:
            portfolios_with_kill_switch = []

        broker_suggestions = self._build_broker_suggestions(idea, brokers)

        suggested_minimum_amount = None
        if broker_suggestions:
            valid_amounts = [
                item["suggested_minimum_stake"]
                for item in broker_suggestions
                if item["suggested_minimum_stake"] is not None and item["suggested_minimum_stake"] > 0
            ]
            if valid_amounts:
                suggested_minimum_amount = min(valid_amounts)

        feedback = getattr(idea, "feedback", None)

        latest_agent_run = None
        if idea.scan_run_id:
            latest_agent_run = (
                AgentRun.objects
                .filter(
                    market_scan_run=idea.scan_run,
                    user=self.request.user,
                )
                .order_by("-created_at")
                .first()
            )

        metrics = self._compute_trade_metrics(idea)

        now = timezone.now()
        expires_in_seconds = None
        expires_in_minutes = None

        if idea.expires_at:
            delta = idea.expires_at - now
            expires_in_seconds = int(delta.total_seconds())
            expires_in_minutes = int(delta.total_seconds() // 60)

        market_snapshot = self._compute_market_snapshot(idea)

        is_deriv_multiplier_symbol = self._is_deriv_multiplier_symbol(idea.symbol)

        ctx.update({
            "market_snapshot": market_snapshot,
            "ai_decision": market_snapshot.get("ai_decision", "WATCH"),
            "ai_reason": market_snapshot.get("ai_reason", ""),
            "recent_market_candles": market_snapshot.get("recent_candles", []),
            "brokers": brokers,
            "broker_suggestions": broker_suggestions,
            "suggested_minimum_amount": suggested_minimum_amount,
            "portfolios": portfolios,
            "portfolios_with_kill_switch": portfolios_with_kill_switch,
            "feedback": feedback,
            "latest_agent_run": latest_agent_run,
            "trade_metrics": metrics,
            "is_expired": idea.is_expired,
            "expires_in_seconds": expires_in_seconds,
            "expires_in_minutes": expires_in_minutes,
            "status_tone": self._status_tone(idea.status),
            "is_deriv_multiplier_symbol": is_deriv_multiplier_symbol,
            "default_deriv_multiplier": 100,
            "default_deriv_duration": 5,
            "default_deriv_duration_unit": "s",
        })

        return ctx

class ExecuteTradeIdeaView(LoginRequiredMixin, UserScopedTradeIdeaMixin, View):
    def _safe_decimal(self, value):
        if value is None or value == "":
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None

    def post(self, request, *args, **kwargs):
        idea = self.get_tradeidea()

        broker_id = request.POST.get("broker_account")
        portfolio_id = request.POST.get("portfolio")
        amount_raw = request.POST.get("amount")

        if not broker_id or not portfolio_id or not amount_raw:
            messages.error(request, "Broker, portefeuille et montant sont requis.")
            return redirect("trading:trade-idea-detail", pk=idea.pk)

        try:
            stake_amount = Decimal(str(amount_raw))
        except (InvalidOperation, ValueError, TypeError):
            messages.error(request, "Montant invalide.")
            return redirect("trading:trade-idea-detail", pk=idea.pk)

        if stake_amount <= 0:
            messages.error(request, "Le montant doit être supérieur à zéro.")
            return redirect("trading:trade-idea-detail", pk=idea.pk)

        broker = BrokerAccount.objects.filter(
            pk=broker_id,
            user=request.user,
            is_active=True,
        ).first()

        portfolio = Portfolio.objects.filter(
            pk=portfolio_id,
            user=request.user,
            is_active=True,
        ).first()

        if not broker:
            messages.error(request, "Broker introuvable.")
            return redirect("trading:trade-idea-detail", pk=idea.pk)

        if not portfolio:
            messages.error(request, "Portefeuille introuvable.")
            return redirect("trading:trade-idea-detail", pk=idea.pk)

        preview = TradeIdeaPreviewService.estimate_minimum_stake(
            idea=idea,
            broker_account=broker,
        )
        suggested_minimum_stake = (
            self._safe_decimal(preview.get("suggested_minimum_stake"))
            if isinstance(preview, dict)
            else None
        )
        broker_minimum_stake = (
            self._safe_decimal(preview.get("broker_minimum_stake"))
            if isinstance(preview, dict)
            else None
        )
        risk_minimum_required = (
            self._safe_decimal(preview.get("risk_minimum_required"))
            if isinstance(preview, dict)
            else None
        )

        try:
            result = TradeIdeaExecutionService.execute(
                idea=idea,
                broker_account=broker,
                portfolio=portfolio,
                stake_amount=stake_amount,
            )

            order = result.get("order") if isinstance(result, dict) else result

            if order is not None:
                messages.success(request, f"Trade exécuté avec succès. Ordre #{order.id} créé.")
            else:
                messages.success(request, "Trade exécuté avec succès.")


        except DatabaseError:
            logger.exception(
                "Erreur DB pendant l'exécution de TradeIdea id=%s symbol=%s",
                getattr(idea, "id", None),
                getattr(idea, "symbol", None),
            )
            raise
        except ValueError as exc:
            error_message = str(exc)
            lower_message = error_message.lower()

            if "minimum broker" in lower_message or "inférieure au minimum" in lower_message:
                if suggested_minimum_stake and suggested_minimum_stake > 0:
                    details = []
                    if broker_minimum_stake is not None:
                        details.append(f"minimum broker théorique : {broker_minimum_stake}")
                    if risk_minimum_required is not None:
                        details.append(f"risque minimal requis : {risk_minimum_required}")

                    detail_text = f" ({' · '.join(details)})" if details else ""

                    messages.error(
                        request,
                        f"Impossible d'exécuter cette idée : le montant saisi reste insuffisant pour {broker.broker}/{broker.mode}. "
                        f"Minimum conseillé : {suggested_minimum_stake}{detail_text}."
                    )
                else:
                    messages.error(
                        request,
                        "Impossible d'exécuter cette idée : le montant saisi reste inférieur au minimum requis par le broker."
                    )
            else:
                messages.error(request, f"Impossible d'exécuter l'idée : {error_message}")

        except Exception as exc:
            messages.error(request, f"Erreur technique d'exécution : {exc}")

        return redirect("trading:trade-idea-detail", pk=idea.pk)


class TradeIdeaLiveFeedView(LoginRequiredMixin, TradeIdeaFilterMixin, View):
    def get(self, request, *args, **kwargs):
        qs = (
            self.get_filtered_queryset()
            .select_related("asset", "timeframe")
            .order_by("-updated_at")[:50]
        )

        ideas = []

        for idea in qs:
            asset = getattr(idea, "asset", None)
            timeframe = getattr(idea, "timeframe", None)

            review = getattr(idea, "review", None)

            asset_class = ""
            if asset:
                try:
                    asset_class = asset.get_asset_class_display()
                except Exception:
                    asset_class = getattr(asset, "asset_class", "") or ""

            timeframe_code = getattr(timeframe, "code", "") if timeframe else ""

            market_context = self._get_market_context(asset, timeframe)
            ai_decision = self._compute_ai_decision(idea)
            ai_reason = self._build_ai_reason(idea, market_context, review)

            ideas.append({
                "id": idea.id,
                "symbol": idea.symbol,
                "asset_class": asset_class,
                "timeframe": timeframe_code,

                "last_price": market_context["last_price"],
                "price_change_pct": market_context["price_change_pct"],
                "market_regime": market_context["market_regime"],
                "trend_direction": market_context["trend_direction"],
                "volatility_level": market_context["volatility_level"],
                "rsi": market_context["rsi"],
                "macd_signal": market_context["macd_signal"],
                "ema_signal": market_context["ema_signal"],
                "atr": market_context["atr"],

                "direction": idea.direction,
                "ai_decision": ai_decision,
                "ai_reason": ai_reason,

                "confidence_score": float(idea.confidence_score or 0),
                "setup_score": float(idea.setup_score or 0),
                "risk_score": float(idea.risk_score or 0),
                "reward_score": float(idea.reward_score or 0),
                "overall_score": float(idea.overall_score or 0),

                "risk_reward_ratio": self._safe_float(getattr(idea, "risk_reward_ratio", None)),
                "suggested_stake": self._safe_float(getattr(idea, "suggested_stake", None)),
                "max_loss": self._safe_float(getattr(idea, "max_loss", None)),
                "expected_profit": self._safe_float(getattr(idea, "expected_profit", None)),

                "status": idea.status,
                "detail_url": reverse("trading:trade-idea-detail", kwargs={"pk": idea.pk}),
                "has_review": bool(review),
                "review_decision": getattr(review, "decision", "") if review else "",
                "updated_at": idea.updated_at.isoformat() if getattr(idea, "updated_at", None) else None,
            })

        return JsonResponse({
            "count": len(ideas),
            "ideas": ideas,
        })

    def _get_market_context(self, asset, timeframe):
        if not asset:
            return self._empty_market_context()

        candles = (
            Candle.objects
            .filter(asset=asset)
            .order_by("-open_time")[:80]
        )

        candles = list(reversed(candles))

        if len(candles) < 2:
            return self._empty_market_context()

        last = candles[-1]
        prev = candles[-2]

        last_price = self._safe_float(last.close)
        prev_price = self._safe_float(prev.close)

        price_change_pct = 0
        if prev_price:
            price_change_pct = ((last_price - prev_price) / prev_price) * 100

        closes = [self._safe_float(c.close) for c in candles if c.close is not None]
        highs = [self._safe_float(c.high) for c in candles if c.high is not None]
        lows = [self._safe_float(c.low) for c in candles if c.low is not None]

        rsi = self._compute_rsi(closes)
        atr = self._compute_atr(highs, lows, closes)

        ema_fast = self._compute_ema(closes, 9)
        ema_slow = self._compute_ema(closes, 21)

        if ema_fast and ema_slow:
            trend_direction = "BULLISH" if ema_fast > ema_slow else "BEARISH"
            ema_signal = "EMA_FAST_ABOVE_SLOW" if ema_fast > ema_slow else "EMA_FAST_BELOW_SLOW"
        else:
            trend_direction = "NEUTRAL"
            ema_signal = "NEUTRAL"

        volatility_level = "HIGH" if atr and last_price and (atr / last_price) > 0.015 else "MEDIUM"
        if atr and last_price and (atr / last_price) < 0.005:
            volatility_level = "LOW"

        market_regime = "TRENDING" if trend_direction in ("BULLISH", "BEARISH") else "RANGING"

        macd_signal = "BULLISH" if ema_fast and ema_slow and ema_fast > ema_slow else "BEARISH"

        return {
            "last_price": round(last_price, 6),
            "price_change_pct": round(price_change_pct, 2),
            "market_regime": market_regime,
            "trend_direction": trend_direction,
            "volatility_level": volatility_level,
            "rsi": round(rsi, 2) if rsi is not None else None,
            "macd_signal": macd_signal,
            "ema_signal": ema_signal,
            "atr": round(atr, 6) if atr is not None else None,
        }

    def _empty_market_context(self):
        return {
            "last_price": None,
            "price_change_pct": None,
            "market_regime": "UNKNOWN",
            "trend_direction": "UNKNOWN",
            "volatility_level": "UNKNOWN",
            "rsi": None,
            "macd_signal": "UNKNOWN",
            "ema_signal": "UNKNOWN",
            "atr": None,
        }

    def _compute_ai_decision(self, idea):
        overall = float(idea.overall_score or 0)
        confidence = float(idea.confidence_score or 0)
        risk = float(idea.risk_score or 0)

        if overall >= 0.75 and confidence >= 0.70 and risk <= 0.45:
            return "EXECUTE"

        if overall >= 0.60 and confidence >= 0.55:
            return "PLAN"

        if risk >= 0.70:
            return "REJECT"

        return "WATCH"

    def _build_ai_reason(self, idea, market_context, review):
        decision = self._compute_ai_decision(idea)

        parts = []

        if market_context["trend_direction"] == "BULLISH":
            parts.append("Tendance haussière détectée.")
        elif market_context["trend_direction"] == "BEARISH":
            parts.append("Tendance baissière détectée.")
        else:
            parts.append("Tendance encore neutre ou insuffisamment confirmée.")

        if market_context["rsi"] is not None:
            rsi = market_context["rsi"]
            if rsi >= 70:
                parts.append("RSI élevé : risque de surachat.")
            elif rsi <= 30:
                parts.append("RSI faible : possible zone de rebond.")
            else:
                parts.append("RSI dans une zone exploitable.")

        if market_context["volatility_level"] == "HIGH":
            parts.append("Volatilité élevée : prudence recommandée.")
        elif market_context["volatility_level"] == "LOW":
            parts.append("Volatilité faible : potentiel limité.")
        else:
            parts.append("Volatilité acceptable.")

        if decision == "EXECUTE":
            parts.append("Décision IA : exécution possible sous validation du risque.")
        elif decision == "PLAN":
            parts.append("Décision IA : opportunité à préparer, confirmation recommandée.")
        elif decision == "REJECT":
            parts.append("Décision IA : risque trop élevé.")
        else:
            parts.append("Décision IA : surveillance uniquement.")

        if review:
            parts.append(f"Review : {getattr(review, 'decision', '')}.")

        return " ".join(parts)

    def _safe_float(self, value, default=0.0):
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def _compute_ema(self, values, period):
        if not values or len(values) < period:
            return None

        k = 2 / (period + 1)
        ema = values[0]

        for price in values[1:]:
            ema = price * k + ema * (1 - k)

        return ema

    def _compute_rsi(self, closes, period=14):
        if len(closes) <= period:
            return None

        gains = []
        losses = []

        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            if diff >= 0:
                gains.append(diff)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(diff))

        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period

        if avg_loss == 0:
            return 100

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _compute_atr(self, highs, lows, closes, period=14):
        if len(highs) <= period or len(lows) <= period or len(closes) <= period:
            return None

        true_ranges = []

        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            true_ranges.append(tr)

        if len(true_ranges) < period:
            return None

        return sum(true_ranges[-period:]) / period


class TradeIdeaApproveView(LoginRequiredMixin, UserScopedTradeIdeaMixin, View):
    def post(self, request, pk):
        idea = self.get_tradeidea()

        if idea.status in ["EXECUTED", "EXPIRED", "CANCELLED"]:
            messages.warning(request, "Cette idée ne peut plus être approuvée.")
            return redirect("trading:trade-idea-detail", pk=idea.pk)

        idea.status = "APPROVED"
        idea.save(update_fields=["status", "updated_at"])

        messages.success(request, "Idée approuvée.")
        return redirect("trading:trade-idea-detail", pk=idea.pk)


class TradeIdeaRejectView(LoginRequiredMixin, UserScopedTradeIdeaMixin, View):
    def post(self, request, pk):
        idea = self.get_tradeidea()

        if idea.status in ["EXECUTED", "EXPIRED", "CANCELLED"]:
            messages.warning(request, "Cette idée ne peut plus être rejetée.")
            return redirect("trading:trade-idea-detail", pk=idea.pk)

        idea.status = "REJECTED"
        idea.save(update_fields=["status", "updated_at"])

        messages.success(request, "Idée rejetée.")
        return redirect("trading:trade-idea-detail", pk=idea.pk)


class TradeIdeaAutoTradeView(LoginRequiredMixin, UserScopedTradeIdeaMixin, View):
    def post(self, request, pk):
        idea = self.get_tradeidea()

        broker_id = request.POST.get("broker_account")
        portfolio_id = request.POST.get("portfolio")
        amount_raw = request.POST.get("amount", "10")

        if not broker_id or not portfolio_id:
            messages.error(request, "Broker et portefeuille requis.")
            return redirect("trading:trade-idea-detail", pk=idea.pk)

        broker = get_object_or_404(
            BrokerAccount,
            pk=broker_id,
            user=request.user,
            is_active=True,
        )
        portfolio = get_object_or_404(
            Portfolio,
            pk=portfolio_id,
            user=request.user,
            is_active=True,
        )

        try:
            amount = Decimal(str(amount_raw))
        except (InvalidOperation, TypeError, ValueError):
            messages.error(request, "Montant invalide.")
            return redirect("trading:trade-idea-detail", pk=idea.pk)

        if amount <= 0:
            messages.error(request, "Le montant doit être supérieur à zéro.")
            return redirect("trading:trade-idea-detail", pk=idea.pk)

        # ── Vérification mode du broker avant exécution ────────────────
        # En PAPER, l'ordre est simulé localement (PaperBrokerAdapter) et
        # n'atteint JAMAIS le broker. C'est le scénario qui a produit
        # "Ordre #41 créé" sans aucune trace côté Deriv.
        if broker.mode == "PAPER":
            if broker.broker == "DERIV" and getattr(broker, "deriv_token", None):
                messages.warning(
                    request,
                    "Le compte Deriv est configuré en mode PAPER : l'ordre sera "
                    "simulé localement et ne sera PAS envoyé à Deriv. "
                    "Pour exécuter sur Deriv (demo ou réel), passez ce compte en "
                    "mode LIVE depuis Brokers → modifier le compte. "
                    "Le type de compte Deriv (demo/réel) est contrôlé séparément "
                    "par le champ « deriv_account_type »."
                )
            else:
                messages.info(
                    request,
                    "Mode PAPER actif : l'ordre est simulé localement, "
                    "aucun appel broker ne sera effectué."
                )

        # ── Décharge utilisateur (override risque) ──────────────────
        # Si l'utilisateur a coché la case « Je passe outre, j'assume
        # le risque » dans le formulaire (ou s'il a re-soumis depuis le
        # bandeau « Forcer l'exécution »), on transmet l'override au
        # service d'exécution. La case est ignorée pour les blocages
        # HARD (kill switch en LIVE, profil interdisant le live ou le
        # short) côté risque.
        risk_override_raw = (request.POST.get("risk_override") or "").strip().lower()
        risk_override = risk_override_raw in {"1", "true", "on", "yes", "oui"}
        risk_override_reason = (request.POST.get("risk_override_reason") or "").strip()[:500]

        # ── Contexte réseau pour l'audit override ────────────────────────
        # On préfère X-Forwarded-For (Nginx/proxy) si présent, sinon REMOTE_ADDR.
        _xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
        risk_override_ip = (_xff.split(",")[0].strip() if _xff else request.META.get("REMOTE_ADDR", ""))[:45]
        risk_override_user_agent = request.META.get("HTTP_USER_AGENT", "")[:512]

        # ── Détection préventive d'un kill switch actif ──────────────
        try:
            from risk.services import RiskGuardService
            if RiskGuardService.has_active_kill_switch(portfolio):
                # Kill switch en LIVE = HARD block, non franchissable même
                # avec override. On dirige l'utilisateur vers le bandeau
                # de résolution placé dans la page de l'idée.
                if not RiskGuardService.is_paper_or_demo(portfolio):
                    resolve_url = reverse(
                        "dashboard:resolve_kill_switch",
                        kwargs={"portfolio_id": portfolio.id},
                    )
                    messages.error(
                        request,
                        "Kill switch actif sur le portefeuille "
                        f"« {portfolio.name} ». L'exécution est bloquée. "
                        "Lève-le via le bandeau rouge en haut de la page "
                        "(bouton « Résoudre »), puis relance l'idée. "
                        f"URL directe : {resolve_url}"
                    )
                    return redirect("trading:trade-idea-detail", pk=idea.pk)
        except Exception:
            pass

        try:
            advice = PortfolioAdvisorAgent.advise(portfolio)

            if getattr(advice, "action", "") == "BLOCK_NEW_POSITIONS":
                reason = getattr(advice, "reason", "Risque portefeuille trop élevé.")
                # Le PortfolioAdvisorAgent est un blocage SOFT lui aussi :
                # si l'utilisateur a explicitement coché l'override, on
                # laisse passer (en logguant). Sinon on bloque proprement.
                if not risk_override:
                    messages.error(
                        request,
                        f"L'agent de risque portefeuille recommande de "
                        f"NE PAS ouvrir de nouvelle position : {reason} "
                        f"Tu peux malgré tout cocher « Forcer l'exécution » "
                        f"plus bas pour passer outre, sous ta responsabilité."
                    )
                    return redirect("trading:trade-idea-detail", pk=idea.pk)
                else:
                    messages.warning(
                        request,
                        "Override accepté : tu passes outre la recommandation "
                        f"du PortfolioAdvisorAgent ({reason}). La trace de "
                        f"cette décision est consignée dans l'audit."
                    )

            result = TradeIdeaExecutionService.execute(
                idea=idea,
                broker_account=broker,
                portfolio=portfolio,
                stake_amount=amount,
                risk_override=risk_override,
                risk_override_reason=risk_override_reason,
                risk_override_user_id=request.user.id,
                risk_override_ip=risk_override_ip,
                risk_override_user_agent=risk_override_user_agent,
            )

            order = result.get("order") if isinstance(result, dict) else None
            if order is not None:
                broker_order_id = getattr(order, "broker_order_id", None) or "—"
                # Note d'override visible dans la confirmation, pour bien
                # rappeler à l'utilisateur qu'il a pris une décision active.
                override_suffix = ""
                if risk_override:
                    override_suffix = (
                        " [override risque appliqué — tu as accepté la "
                        "responsabilité de ce trade]"
                    )

                if broker.mode == "PAPER":
                    messages.success(
                        request,
                        f"Auto-trading lancé en mode PAPER. Ordre #{order.id} "
                        f"simulé localement (broker_order_id={broker_order_id}). "
                        f"Aucun ordre n'a été envoyé à {broker.broker}."
                        f"{override_suffix}"
                    )
                else:
                    messages.success(
                        request,
                        f"Auto-trading lancé en mode LIVE. Ordre #{order.id} "
                        f"envoyé à {broker.broker} "
                        f"(broker_order_id={broker_order_id}, statut={order.status})."
                        f"{override_suffix}"
                    )
            else:
                messages.success(request, "Auto-trading lancé avec succès.")
        except Exception as exc:
            err_str = str(exc)

            if "Kill switch" in err_str:
                resolve_url = reverse(
                    "dashboard:resolve_kill_switch",
                    kwargs={"portfolio_id": portfolio.id},
                )
                messages.error(
                    request,
                    "Kill switch actif : exécution bloquée. Lève-le depuis "
                    f"la page de l'idée (bandeau rouge en haut), puis relance. "
                    f"URL directe : {resolve_url}"
                )
            else:
                # Tous les blocages SOFT (max positions, drawdown, etc.)
                # remontent ici. On termine le message par une indication
                # claire de l'option « Forcer » disponible juste en bas.
                hint = ""
                if not risk_override:
                    hint = (
                        " — Si tu acceptes le risque, coche « Forcer "
                        "l'exécution » dans le formulaire et relance."
                    )
                messages.error(
                    request,
                    f"Exécution bloquée : {err_str}{hint}"
                )

        return redirect("trading:trade-idea-detail", pk=idea.pk)
