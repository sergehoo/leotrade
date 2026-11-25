# /Users/ogahserge/Documents/leoTrade/risk/services.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, ROUND_DOWN
from typing import Optional

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from core.realtime import RealtimeBroadcastService
from execution.notifications import TradingNotificationService
from portfolio.models import Position
from portfolio.services import PortfolioService
from .models import (
    RiskProfile,
    DailyRiskState,
    WeeklyRiskState,
    MonthlyRiskState,
    RiskDecision,
    KillSwitchEvent,
)


def _d(value, default="0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


@dataclass
class SizingResult:
    requested_stake: Decimal
    approved_stake: Decimal
    quantity: Decimal
    notional: Decimal
    risk_amount: Decimal
    stop_distance: Decimal
    leverage: Decimal
    reason: str


@dataclass
class RiskApprovalResult:
    decision: str
    approved_stake: Decimal
    approved_quantity: Decimal
    approved_notional: Decimal
    expected_loss: Decimal
    expected_gain: Decimal
    risk_reward_ratio: Decimal
    blocking_reason: str
    payload: dict
    # Catégorisation du blocage pour l'UX (set quand decision in {BLOCK, REJECT}).
    #   "HARD"     → non franchissable (kill switch, profil interdit le live, etc.)
    #   "SOFT"     → l'utilisateur peut passer outre via une décharge explicite
    #                ("override") qui sera tracée dans le RiskDecision.payload.
    #   "REQUIRED" → champ manquant côté idée (stop loss obligatoire, etc.)
    block_severity: str = ""
    # Code court machine-friendly pour l'UI (ex: "MAX_OPEN_POSITIONS").
    block_code: str = ""


class RiskStateService:
    @staticmethod
    def _week_start(date_value):
        return date_value - timedelta(days=date_value.weekday())

    @staticmethod
    def _month_start(date_value):
        return date_value.replace(day=1)

    @staticmethod
    def _is_deriv_portfolio(portfolio) -> bool:
        broker = getattr(portfolio, "broker_account", None)
        broker_name = str(getattr(broker, "broker", "") or "").upper()
        return broker_name == "DERIV"

    @staticmethod
    def _safe_equity_current(portfolio):
        equity_current = _d(portfolio.equity)
        balance = _d(portfolio.current_balance)

        if equity_current <= 0 and balance > 0:
            return balance

        if balance > 0 and abs(equity_current) > balance * Decimal("10"):
            return balance

        return equity_current

    @classmethod
    def _safe_equity_open(cls, portfolio, first_snapshot):
        equity_current = cls._safe_equity_current(portfolio)
        equity_open = _d(first_snapshot.equity) if first_snapshot else equity_current

        if equity_current > 0 and equity_open > equity_current * Decimal("10"):
            equity_open = equity_current

        if equity_open <= 0:
            equity_open = equity_current

        return equity_open

    @staticmethod
    def _safe_loss_percent(equity_open: Decimal, equity_current: Decimal) -> tuple[Decimal, Decimal]:
        equity_open = _d(equity_open)
        equity_current = _d(equity_current)

        if equity_open <= 0:
            return Decimal("0.00"), Decimal("0.0000")

        drawdown_amount = max(Decimal("0.00"), equity_open - equity_current)
        loss_pct = (drawdown_amount / equity_open) * Decimal("100")

        # Protection contre les états contaminés : une perte > 100 % est anormale
        # pour ce risk-state interne. On neutralise au lieu de bloquer le trading.
        if loss_pct > Decimal("100"):
            return Decimal("0.00"), Decimal("0.0000")

        return drawdown_amount, loss_pct.quantize(Decimal("0.0001"))

    @classmethod
    @transaction.atomic
    def refresh_daily_state(cls, portfolio):
        portfolio = PortfolioService.refresh_portfolio_metrics(portfolio)
        today = timezone.localdate()

        first_snapshot = portfolio.snapshots.filter(
            snapshot_time__date=today
        ).order_by("snapshot_time").first()

        safe_equity_current = cls._safe_equity_current(portfolio)
        safe_equity_open = cls._safe_equity_open(portfolio, first_snapshot)

        state, _ = DailyRiskState.objects.get_or_create(
            portfolio=portfolio,
            day=today,
            defaults={"equity_open": safe_equity_open},
        )

        # Corrige un DailyRiskState déjà contaminé.
        if (
            _d(state.equity_open) <= 0
            or _d(state.equity_open) > safe_equity_current * Decimal("10")
            or _d(state.total_loss_percent) > Decimal("100")
        ):
            state.equity_open = safe_equity_open

        state.realized_pnl = _d(portfolio.realized_pnl)
        state.unrealized_pnl = _d(portfolio.unrealized_pnl)
        state.equity_current = safe_equity_current
        state.open_positions_count = portfolio.positions.filter(
            status__in=["OPEN", "PARTIALLY_CLOSED"]
        ).count()

        loss_amount, loss_percent = cls._safe_loss_percent(
            state.equity_open,
            state.equity_current,
        )

        state.total_loss_amount = loss_amount
        state.total_loss_percent = loss_percent

        state.payload = {
            "portfolio_equity": str(portfolio.equity),
            "portfolio_balance": str(portfolio.current_balance),
            "safe_equity_open": str(safe_equity_open),
            "safe_equity_current": str(safe_equity_current),
            "drawdown_percent": portfolio.current_drawdown_percent,
            "first_snapshot_id": getattr(first_snapshot, "id", None),
            "is_deriv_portfolio": cls._is_deriv_portfolio(portfolio),
        }

        state.save()
        return state

    @classmethod
    @transaction.atomic
    def refresh_weekly_state(cls, portfolio):
        portfolio = PortfolioService.refresh_portfolio_metrics(portfolio)

        today = timezone.localdate()
        week_start = cls._week_start(today)

        first_snapshot = portfolio.snapshots.filter(
            snapshot_time__date__gte=week_start,
            snapshot_time__date__lte=today,
        ).order_by("snapshot_time").first()

        safe_equity_current = cls._safe_equity_current(portfolio)
        safe_equity_open = cls._safe_equity_open(portfolio, first_snapshot)

        state, _ = WeeklyRiskState.objects.get_or_create(
            portfolio=portfolio,
            week_start=week_start,
            defaults={"equity_open": safe_equity_open},
        )

        # Corrige un WeeklyRiskState déjà contaminé.
        if (
            _d(state.equity_open) <= 0
            or _d(state.equity_open) > safe_equity_current * Decimal("10")
            or _d(state.total_loss_percent) > Decimal("100")
        ):
            state.equity_open = safe_equity_open

        state.realized_pnl = _d(portfolio.realized_pnl)
        state.unrealized_pnl = _d(portfolio.unrealized_pnl)
        state.equity_current = safe_equity_current

        loss_amount, loss_percent = cls._safe_loss_percent(
            state.equity_open,
            state.equity_current,
        )

        state.total_loss_amount = loss_amount
        state.total_loss_percent = loss_percent

        state.payload = {
            "portfolio_equity": str(portfolio.equity),
            "portfolio_balance": str(portfolio.current_balance),
            "safe_equity_open": str(safe_equity_open),
            "safe_equity_current": str(safe_equity_current),
            "drawdown_percent": portfolio.current_drawdown_percent,
            "first_snapshot_id": getattr(first_snapshot, "id", None),
            "is_deriv_portfolio": cls._is_deriv_portfolio(portfolio),
        }

        state.save()
        return state

    @classmethod
    @transaction.atomic
    def refresh_monthly_state(cls, portfolio):
        portfolio = PortfolioService.refresh_portfolio_metrics(portfolio)

        today = timezone.localdate()
        month_start = cls._month_start(today)

        first_snapshot = portfolio.snapshots.filter(
            snapshot_time__date__gte=month_start,
            snapshot_time__date__lte=today,
        ).order_by("snapshot_time").first()

        safe_equity_current = cls._safe_equity_current(portfolio)
        safe_equity_open = cls._safe_equity_open(portfolio, first_snapshot)

        state, _ = MonthlyRiskState.objects.get_or_create(
            portfolio=portfolio,
            month_start=month_start,
            defaults={"equity_open": safe_equity_open},
        )

        # Corrige un MonthlyRiskState déjà contaminé.
        if (
            _d(state.equity_open) <= 0
            or _d(state.equity_open) > safe_equity_current * Decimal("10")
            or _d(state.total_loss_percent) > Decimal("100")
        ):
            state.equity_open = safe_equity_open

        state.realized_pnl = _d(portfolio.realized_pnl)
        state.unrealized_pnl = _d(portfolio.unrealized_pnl)
        state.equity_current = safe_equity_current

        loss_amount, loss_percent = cls._safe_loss_percent(
            state.equity_open,
            state.equity_current,
        )

        state.total_loss_amount = loss_amount
        state.total_loss_percent = loss_percent

        state.payload = {
            "portfolio_equity": str(portfolio.equity),
            "portfolio_balance": str(portfolio.current_balance),
            "safe_equity_open": str(safe_equity_open),
            "safe_equity_current": str(safe_equity_current),
            "drawdown_percent": portfolio.current_drawdown_percent,
            "first_snapshot_id": getattr(first_snapshot, "id", None),
            "is_deriv_portfolio": cls._is_deriv_portfolio(portfolio),
        }

        state.save()
        return state


class PositionSizingService:
    @staticmethod
    def _quantize_step(value: Decimal, step: Decimal) -> Decimal:
        if step <= 0:
            return value
        ratio = (value / step).quantize(Decimal("1"), rounding=ROUND_DOWN)
        return ratio * step

    @classmethod
    def compute(
            cls,
            *,
            portfolio,
            risk_profile: RiskProfile,
            entry_price: Decimal,
            stop_loss: Decimal,
            requested_stake: Decimal,
            min_qty: Decimal = Decimal("0.00000001"),
            qty_step: Decimal = Decimal("0.00000001"),
            min_notional: Decimal = Decimal("0"),
            leverage: Decimal = Decimal("1"),
            # ── Capital Preservation First (optionnels, rétrocompatibles) ──
            # instrument_tier : applique le plafond DUR de risque de la classe
            #   (CORE 0,50 % / VOLATILE 0,25 % / SPECULATIVE 0,25 %). Ne peut
            #   que RÉDUIRE le risque du profil, jamais l'augmenter.
            # atr : volatilité de l'instrument en unités de prix (Average True
            #   Range). Fournie ⇒ active le volatility targeting.
            # target_vol_pct : part d'équité que l'on accepte de voir bouger sur
            #   un mouvement de 1 ATR. Par défaut (None) = le risque EFFECTIF
            #   après plafond de classe : sinon un budget figé à 1 % laisserait
            #   un mouvement d'1 ATR coûter 4x le plafond d'un instrument
            #   SPECULATIVE (0,25 %), ce que la protection est censée empêcher.
            instrument_tier: str | None = None,
            atr: Decimal | None = None,
            target_vol_pct: Decimal | None = None,
    ) -> SizingResult:
        if requested_stake <= 0:
            raise ValueError("Le stake demandé doit être supérieur à zéro.")
        if entry_price <= 0:
            raise ValueError("Le prix d'entrée doit être supérieur à zéro.")
        if stop_loss is None or stop_loss <= 0:
            raise ValueError("Le stop loss doit être défini et supérieur à zéro.")

        available_cash = _d(portfolio.available_cash)
        if available_cash <= 0:
            raise ValueError("Le portefeuille ne dispose pas de cash disponible.")

        equity = _d(portfolio.equity)
        if equity <= 0:
            raise ValueError("L'equity du portefeuille doit être supérieure à zéro.")

        # Mission 1 — Protéger : le risque par trade est plafonné par le profil
        # ET par la classe d'instrument. Le plus contraignant gagne.
        profile_risk_pct = _d(risk_profile.max_risk_per_trade)
        tier_note = ""
        if instrument_tier:
            from .instruments import effective_risk_pct, policy_for_tier

            tier_policy = policy_for_tier(instrument_tier)
            capped_risk_pct = effective_risk_pct(profile_risk_pct, tier_policy)
            if capped_risk_pct < profile_risk_pct:
                tier_note = (
                    f" Plafond classe {tier_policy.tier} appliqué : "
                    f"{profile_risk_pct}% → {capped_risk_pct}%."
                )
            profile_risk_pct = capped_risk_pct

        max_risk_per_trade_percent = profile_risk_pct / Decimal("100")
        risk_amount = equity * max_risk_per_trade_percent

        if risk_amount <= 0:
            raise ValueError("Le profil de risque n'autorise aucun risque par trade.")

        stop_distance = abs(entry_price - stop_loss)
        if stop_distance <= 0:
            raise ValueError("La distance au stop loss doit être supérieure à zéro.")

        risk_based_quantity = risk_amount / stop_distance
        stake_based_quantity = requested_stake / entry_price
        cash_based_quantity = available_cash / entry_price

        candidates = [risk_based_quantity, stake_based_quantity, cash_based_quantity]

        # Volatility targeting — borne la quantité pour qu'un mouvement de
        # 1 ATR ne fasse pas bouger l'équité de plus de target_vol_pct.
        # Complète le stop-based sizing : protège aussi quand le stop est très
        # serré sur un instrument très volatil (stop-out quasi certain).
        vol_note = ""
        atr_value = _d(atr) if atr is not None else Decimal("0")
        if atr_value > 0:
            # Budget de volatilité aligné sur le risque effectif (déjà plafonné
            # par la classe) sauf surcharge explicite de l'appelant.
            vol_pct = _d(target_vol_pct) if target_vol_pct is not None else profile_risk_pct
            vol_budget = equity * (vol_pct / Decimal("100"))
            vol_based_quantity = vol_budget / atr_value
            candidates.append(vol_based_quantity)
            if vol_based_quantity < min(risk_based_quantity, stake_based_quantity):
                vol_note = (
                    f" Volatility targeting actif (ATR={atr_value}, "
                    f"cible={vol_pct}%) : quantité bornée à "
                    f"{vol_based_quantity:.8f}."
                )

        raw_quantity = min(candidates)
        quantity = cls._quantize_step(raw_quantity, qty_step)

        broker_min_stake = max(
            min_notional,
            (min_qty * entry_price)
        ).quantize(Decimal("0.01"))

        risk_min_stake = (min_qty * entry_price).quantize(Decimal("0.01"))
        risk_needed_for_min_qty = (min_qty * stop_distance).quantize(Decimal("0.01"))

        if risk_based_quantity < min_qty:
            raise ValueError(
                "Quantité inférieure au minimum broker à cause de la contrainte de risque. "
                f"Risque autorisé={risk_amount:.2f}, "
                f"distance stop={stop_distance:.2f}, "
                f"quantité max par risque={risk_based_quantity:.8f}, "
                f"min_qty broker={min_qty}. "
                f"Pour atteindre le minimum broker, il faut au moins un risque autorisé de {risk_needed_for_min_qty:.2f} "
                f"ou un stop loss plus proche."
            )

        if stake_based_quantity < min_qty:
            raise ValueError(
                "Quantité inférieure au minimum broker à cause du montant engagé. "
                f"Montant saisi={requested_stake:.2f}, "
                f"prix entrée={entry_price:.2f}, "
                f"quantité max par stake={stake_based_quantity:.8f}, "
                f"min_qty broker={min_qty}. "
                f"Montant minimum broker théorique requis={broker_min_stake:.2f}."
            )

        if cash_based_quantity < min_qty:
            raise ValueError(
                "Quantité inférieure au minimum broker à cause du cash disponible. "
                f"Cash disponible={available_cash:.2f}, "
                f"prix entrée={entry_price:.2f}, "
                f"quantité max par cash={cash_based_quantity:.8f}, "
                f"min_qty broker={min_qty}."
            )

        if quantity < min_qty:
            raise ValueError(
                "La quantité calculée est inférieure au minimum broker après arrondi. "
                f"Quantité brute={raw_quantity:.8f}, "
                f"quantité arrondie={quantity:.8f}, "
                f"min_qty={min_qty}, "
                f"qty_step={qty_step}."
            )

        notional = quantity * entry_price
        if min_notional and notional < min_notional:
            raise ValueError(
                "Le notionnel calculé est inférieur au minimum broker. "
                f"Notionnel={notional:.2f}, min_notional={min_notional}."
            )

        approved_stake = min(notional, available_cash)

        return SizingResult(
            requested_stake=requested_stake,
            approved_stake=approved_stake,
            quantity=quantity,
            notional=notional,
            risk_amount=risk_amount,
            stop_distance=stop_distance,
            leverage=leverage,
            reason=(
                "Sizing validé via risque + stake + cash + contraintes broker. "
                f"risk_qty={risk_based_quantity:.8f}, "
                f"stake_qty={stake_based_quantity:.8f}, "
                f"cash_qty={cash_based_quantity:.8f}, "
                f"raw_qty={raw_quantity:.8f}, "
                f"final_qty={quantity:.8f}."
                f"{tier_note}{vol_note}"
            ),
        )


class RiskGuardService:

    @staticmethod
    def is_paper_or_demo(portfolio) -> bool:
        portfolio_mode = str(getattr(portfolio, "mode", "") or "").upper()
        broker = getattr(portfolio, "broker_account", None)
        broker_mode = str(getattr(broker, "mode", "") or "").upper()
        return portfolio_mode in {"PAPER", "DEMO"} or broker_mode in {"PAPER", "DEMO"}

    @staticmethod
    def is_deriv_broker(portfolio) -> bool:
        broker = getattr(portfolio, "broker_account", None)
        broker_name = str(getattr(broker, "broker", "") or "").upper()
        return broker_name == "DERIV"

    @staticmethod
    def get_default_profile(portfolio) -> RiskProfile:
        profile = portfolio.risk_profiles.filter(is_active=True, is_default=True).first()
        if profile:
            return profile

        profile, _ = RiskProfile.objects.get_or_create(
            user=portfolio.user,
            portfolio=portfolio,
            name="Default Risk Profile",
            defaults={
                "is_active": True,
                "is_default": True,
            },
        )
        return profile

    @classmethod
    def symbol_open_exposure(cls, portfolio, symbol: str) -> Decimal:
        exposure_field = cls.position_risk_exposure_field(portfolio, symbol)

        total = (
            portfolio.positions
            .filter(status__in=["OPEN", "PARTIALLY_CLOSED"], symbol=symbol)
            .aggregate(total=Sum(exposure_field))
            .get("total")
        )
        return _d(total)

    @classmethod
    def position_risk_exposure_field(cls, portfolio, symbol: str = "") -> str:
        if cls.is_deriv_trade(portfolio, symbol):
            return "margin_used"
        return "exposure_value"

    @classmethod
    def asset_class_open_exposure(cls, portfolio, asset_class: str, symbol: str = "") -> Decimal:
        exposure_field = cls.position_risk_exposure_field(portfolio, symbol)

        total = (
            portfolio.positions
            .filter(status__in=["OPEN", "PARTIALLY_CLOSED"], asset__asset_class=asset_class)
            .aggregate(total=Sum(exposure_field))
            .get("total")
        )
        return _d(total)

    @classmethod
    def correlated_exposure(cls, portfolio, asset, symbol: str = "", threshold: float = 0.80) -> Decimal:
        if not asset:
            return Decimal("0.00")

        exposure_field = cls.position_risk_exposure_field(portfolio, symbol)

        corr_rows = portfolio.position_correlations.filter(
            asset_a=asset
        ) | portfolio.position_correlations.filter(asset_b=asset)

        correlated_assets = set()

        for row in corr_rows:
            if abs(float(row.correlation_value or 0.0)) >= threshold:
                correlated_assets.add(row.asset_a_id)
                correlated_assets.add(row.asset_b_id)

        total = (
            portfolio.positions
            .filter(
                status__in=["OPEN", "PARTIALLY_CLOSED"],
                asset_id__in=correlated_assets,
            )
            .aggregate(total=Sum(exposure_field))
            .get("total")
        )

        return _d(total)

    @classmethod
    def has_active_kill_switch(cls, portfolio) -> bool:
        return portfolio.kill_switch_events.filter(is_active=True).exists()

    @classmethod
    @transaction.atomic
    def trigger_kill_switch(cls, portfolio, risk_profile: RiskProfile, reason_code: str, reason: str,
                            payload: dict | None = None):
        existing = (
            KillSwitchEvent.objects
            .select_for_update()
            .filter(portfolio=portfolio, is_active=True)
            .order_by("-triggered_at")
            .first()
        )
        if existing is not None:
            return existing

        event = KillSwitchEvent.objects.create(
            portfolio=portfolio,
            risk_profile=risk_profile,
            reason_code=reason_code,
            reason=reason,
            payload=payload or {},
            is_active=True,
        )

        # Notification multicanale (critique : email + in-app + SMS/WhatsApp
        # si autorisés). dedupe_key : une seule notif par event kill switch.
        from notifications.shortcuts import notify
        notify(
            portfolio.user, "KILL_SWITCH_ACTIVATED",
            title=f"Kill switch activé — {portfolio.name}",
            message=(
                f"Le kill switch vient d'être déclenché sur « {portfolio.name} » : "
                f"{reason} Plus aucun nouvel ordre ne sera exécuté tant qu'il est actif."
            ),
            payload={
                "portfolio_id": portfolio.id,
                "portfolio_name": portfolio.name,
                "reason_code": reason_code,
                "reason": reason,
            },
            dedupe_key=f"kill_switch:{event.id}",
        )
        # Les limites de perte ont leur propre événement (en plus du kill switch)
        if reason_code in ("DAILY_LOSS_LIMIT", "WEEKLY_LOSS_LIMIT", "MONTHLY_LOSS_LIMIT", "HIGH_DRAWDOWN"):
            notify(
                portfolio.user, reason_code if reason_code != "HIGH_DRAWDOWN" else "HIGH_DRAWDOWN",
                title=f"Limite de risque atteinte — {portfolio.name}",
                message=reason,
                payload={"portfolio_id": portfolio.id, "portfolio_name": portfolio.name,
                         "reason_code": reason_code},
                dedupe_key=f"loss_limit:{reason_code}:{portfolio.id}:{timezone.localdate().isoformat()}",
            )

        daily = RiskStateService.refresh_daily_state(portfolio)
        weekly = RiskStateService.refresh_weekly_state(portfolio)
        monthly = RiskStateService.refresh_monthly_state(portfolio)

        monthly.kill_switch_triggered = True
        monthly.blocked_new_positions = True
        monthly.save(update_fields=["kill_switch_triggered", "blocked_new_positions", "updated_at"])

        daily.kill_switch_triggered = True
        daily.blocked_new_positions = True
        daily.save(update_fields=["kill_switch_triggered", "blocked_new_positions", "updated_at"])

        weekly.kill_switch_triggered = True
        weekly.blocked_new_positions = True
        weekly.save(update_fields=["kill_switch_triggered", "blocked_new_positions", "updated_at"])
        TradingNotificationService.notify_error(
            user_id=portfolio.user_id,
            message=f"Kill switch activé: {reason}",
            payload={
                "portfolio_id": portfolio.id,
                "reason_code": reason_code,
            },
        )

        RealtimeBroadcastService.broadcast_dashboard_update(
            user_id=portfolio.user_id,
            payload={
                "kind": "kill_switch_triggered",
                "portfolio_id": portfolio.id,
                "reason_code": reason_code,
                "reason": reason,
            },
        )
        return event

    @classmethod
    def is_paper_or_demo(cls, portfolio) -> bool:
        portfolio_mode = str(getattr(portfolio, "mode", "") or "").upper()
        broker_mode = str(getattr(getattr(portfolio, "broker_account", None), "mode", "") or "").upper()

        return portfolio_mode in {"PAPER", "DEMO"} or broker_mode in {"PAPER", "DEMO"}

    @classmethod
    @transaction.atomic
    def resolve_kill_switch(cls, portfolio):
        active_events = portfolio.kill_switch_events.filter(is_active=True)
        now = timezone.now()
        had_active = active_events.exists()
        for event in active_events:
            event.is_active = False
            event.resolved_at = now
            event.save(update_fields=["is_active", "resolved_at", "updated_at"])

        if had_active:
            from notifications.shortcuts import notify
            notify(
                portfolio.user, "KILL_SWITCH_DEACTIVATED",
                title=f"Kill switch désactivé — {portfolio.name}",
                message=(
                    f"Le kill switch de « {portfolio.name} » a été levé : "
                    f"le trading peut reprendre. Reste prudent sur les premières entrées."
                ),
                payload={"portfolio_id": portfolio.id, "portfolio_name": portfolio.name},
            )

        RealtimeBroadcastService.broadcast_dashboard_update(
            user_id=portfolio.user_id,
            payload={
                "kind": "kill_switch_resolved",
                "portfolio_id": portfolio.id,
                "resolved_count": active_events.count(),
            },
        )
        return active_events.count()

    @classmethod
    def is_paper_or_demo(cls, portfolio) -> bool:
        portfolio_mode = str(getattr(portfolio, "mode", "") or "").upper()
        broker_mode = str(getattr(getattr(portfolio, "broker_account", None), "mode", "") or "").upper()

        return portfolio_mode in {"PAPER", "DEMO"} or broker_mode in {"PAPER", "DEMO"}

    # ─────────────────────────────────────────────────────────────────
    #  Catégorisation des blocages — utilisée par l'UI pour proposer
    #  (ou non) un bouton « passer outre » assorti d'une décharge.
    # ─────────────────────────────────────────────────────────────────
    HARD_BLOCK_CODES = {
        "KILL_SWITCH_LIVE",  # kill switch actif en LIVE
        "LIVE_TRADING_FORBIDDEN",  # le profil interdit explicitement le LIVE
        "SHORT_FORBIDDEN",  # le profil interdit le short
    }

    @staticmethod
    def _humanize_pct(value, suffix: str = " %") -> str:
        try:
            return f"{Decimal(str(value)).quantize(Decimal('0.01'))}{suffix}"
        except Exception:
            return f"{value}{suffix}"

    @classmethod
    def _build_block(
            cls,
            *,
            block_code: str,
            severity: str,
            reason: str,
            payload: dict,
            decision: str = "BLOCK",
    ) -> RiskApprovalResult:
        return RiskApprovalResult(
            decision=decision,
            approved_stake=Decimal("0.00"),
            approved_quantity=Decimal("0"),
            approved_notional=Decimal("0.00"),
            expected_loss=Decimal("0.00"),
            expected_gain=Decimal("0.00"),
            risk_reward_ratio=Decimal("0.00"),
            blocking_reason=reason,
            payload=payload,
            block_severity=severity,
            block_code=block_code,
        )

    @staticmethod
    def is_deriv_symbol(symbol: str) -> bool:
        symbol = str(symbol or "").upper().strip()
        return symbol.startswith((
            "R_", "1HZ", "HZ", "JD", "JUMP",
            "CRASH", "BOOM", "STEP", "VOL",
        ))

    @classmethod
    def is_deriv_trade(cls, portfolio, symbol: str = "") -> bool:
        broker = getattr(portfolio, "broker_account", None)
        broker_name = str(getattr(broker, "broker", "") or "").upper()
        return broker_name == "DERIV" or cls.is_deriv_symbol(symbol)

    @classmethod
    def open_positions_count(cls, portfolio, symbol: str = "") -> int:
        qs = portfolio.positions.filter(
            status__in=["OPEN", "PARTIALLY_CLOSED"]
        )

        if cls.is_deriv_trade(portfolio, symbol):
            qs = qs.exclude(
                broker_position_id__isnull=True
            ).exclude(
                broker_position_id=""
            )

        return qs.count()

    @classmethod
    def validate_trade(
            cls,
            *,
            portfolio,
            symbol: str,
            asset=None,
            side: str,
            requested_stake: Decimal,
            approved_quantity: Decimal,
            approved_notional: Decimal,
            entry_price: Decimal,
            stop_loss: Optional[Decimal],
            take_profit: Optional[Decimal],
            confidence: Optional[Decimal] = None,
            signal=None,
            trade_idea=None,
            risk_override: bool = False,
            risk_override_reason: str = "",
            risk_override_user_id: Optional[int] = None,
            # Contexte réseau — transmis depuis la vue HTTP pour l'audit.
            # Optionnels : les appels internes (Celery, API) peuvent les omettre.
            risk_override_ip: str = "",
            risk_override_user_agent: str = "",
    ) -> RiskApprovalResult:
        """
        Évalue le risque d'un trade.

        Override
        --------
        Si ``risk_override=True``, les blocages SOFT (positions max, exposition,
        loss limits côté DEMO, etc.) sont franchissables. Les blocages HARD
        restent bloquants quoi qu'il arrive : kill switch en LIVE, profil
        qui interdit le live ou le short.

        Le motif (``risk_override_reason``) et l'identifiant utilisateur sont
        consignés dans le payload pour audit, sous la clé ``risk_override``.
        Un enregistrement ``RiskOverrideAudit`` est persisté automatiquement
        lorsque le résultat final est APPROVE avec risk_override=True.
        """
        profile = cls.get_default_profile(portfolio)

        daily_state = RiskStateService.refresh_daily_state(portfolio)
        weekly_state = RiskStateService.refresh_weekly_state(portfolio)
        monthly_state = RiskStateService.refresh_monthly_state(portfolio)

        portfolio.refresh_from_db()

        # Réparation anti-drawdown contaminé.
        if _d(portfolio.current_drawdown_percent) > Decimal("100"):
            portfolio.current_drawdown_percent = 0.0
            portfolio.max_drawdown_percent = 0.0
            portfolio.max_equity = portfolio.equity or portfolio.current_balance
            portfolio.save(update_fields=[
                "current_drawdown_percent",
                "max_drawdown_percent",
                "max_equity",
                "updated_at",
            ])

        # Protection anti-données contaminées : une perte > 100 % est anormale.
        if _d(daily_state.total_loss_percent) > Decimal("100"):
            daily_state.total_loss_percent = Decimal("0.0000")
            daily_state.total_loss_amount = Decimal("0.00")
            daily_state.equity_open = daily_state.equity_current
            daily_state.payload = {
                **(daily_state.payload or {}),
                "auto_repaired": True,
                "repair_reason": "daily_loss_percent_above_100",
            }
            daily_state.save(update_fields=[
                "total_loss_percent",
                "total_loss_amount",
                "equity_open",
                "payload",
                "updated_at",
            ])

        if _d(weekly_state.total_loss_percent) > Decimal("100"):
            weekly_state.total_loss_percent = Decimal("0.0000")
            weekly_state.total_loss_amount = Decimal("0.00")
            weekly_state.equity_open = weekly_state.equity_current
            weekly_state.payload = {
                **(weekly_state.payload or {}),
                "auto_repaired": True,
                "repair_reason": "weekly_loss_percent_above_100",
            }
            weekly_state.save(update_fields=[
                "total_loss_percent",
                "total_loss_amount",
                "equity_open",
                "payload",
                "updated_at",
            ])
        asset_class = getattr(asset, "asset_class", None) or "UNKNOWN"
        confidence = _d(confidence, "0")
        requested_stake = _d(requested_stake)
        approved_quantity = _d(approved_quantity)
        approved_notional = _d(approved_notional)
        entry_price = _d(entry_price)
        stop_loss = _d(stop_loss) if stop_loss is not None else None
        take_profit = _d(take_profit) if take_profit is not None else None

        is_demo = cls.is_paper_or_demo(portfolio)
        broker_mode = getattr(getattr(portfolio, "broker_account", None), "mode", "") or "—"

        is_deriv = cls.is_deriv_trade(portfolio, symbol)

        open_positions_count = cls.open_positions_count(
            portfolio=portfolio,
            symbol=symbol,
        )

        payload = {
            "daily_loss_percent": str(daily_state.total_loss_percent),
            "weekly_loss_percent": str(weekly_state.total_loss_percent),
            "portfolio_drawdown_percent": str(portfolio.current_drawdown_percent),
            "open_positions_count": open_positions_count,
            "max_open_positions": profile.max_open_positions,
            "broker_mode": broker_mode,
            "is_paper_or_demo": is_demo,
        }

        # Trace l'override pour audit (toujours, même si non utilisé in-fine).
        if risk_override:
            payload["risk_override"] = {
                "user_id": risk_override_user_id,
                "reason": risk_override_reason or "",
                "applied_to": [],  # rempli ci-dessous quand un check soft est court-circuité
            }

        def _soft_block_or_override(code: str, reason: str):
            """
            Helper : si l'utilisateur a accepté la décharge (risk_override),
            on laisse passer en consignant dans le payload. Sinon on rend
            un BLOCK SOFT exploitable par l'UI.
            """
            if risk_override:
                payload["risk_override"]["applied_to"].append({
                    "code": code,
                    "reason": reason,
                })
                return None  # → on continue la validation
            return cls._build_block(
                block_code=code,
                severity="SOFT",
                reason=reason,
                payload=payload,
            )

        # ── 1. Kill switch ───────────────────────────────────────────
        if cls.has_active_kill_switch(portfolio):
            if not is_demo:
                return cls._build_block(
                    block_code="KILL_SWITCH_LIVE",
                    severity="HARD",
                    reason=(
                        "Le kill switch est actif sur ce portefeuille. "
                        "Pour relancer du trading LIVE tu dois d'abord "
                        "lever le kill switch depuis la page de l'idée "
                        "ou le cockpit premium, puis t'assurer que les "
                        "seuils (perte journalière/hebdo, drawdown) sont "
                        "revenus sous les limites de ton profil de risque."
                    ),
                    payload=payload,
                )
            payload["kill_switch_warning"] = (
                "Kill switch actif — non bloquant car le compte est en PAPER/DEMO."
            )

        # ── 2. Profil interdit le live trading ──────────────────────
        if (not profile.allow_live_trading
                and getattr(portfolio.broker_account, "mode", "") == "LIVE"):
            return cls._build_block(
                block_code="LIVE_TRADING_FORBIDDEN",
                severity="HARD",
                reason=(
                    "Ton profil de risque interdit le trading en LIVE. "
                    "Active « allow_live_trading » dans ton profil "
                    "(page Risk Monitor → modifier le profil) ou bascule "
                    "le compte broker en PAPER pour tester d'abord."
                ),
                payload=payload,
            )

        # ── 3. Profil interdit le short ─────────────────────────────
        if side == "SELL" and not profile.allow_short:
            return cls._build_block(
                block_code="SHORT_FORBIDDEN",
                severity="HARD",
                reason=(
                    "Ton profil de risque interdit les positions courtes "
                    "(SELL/SHORT). Active « allow_short » dans ton profil "
                    "de risque pour autoriser ce sens de trade."
                ),
                payload=payload,
                decision="REJECT",
            )

        # ── 4. Confiance IA insuffisante ────────────────────────────
        if confidence and confidence < _d(profile.min_confidence):
            soft = _soft_block_or_override(
                "AI_CONFIDENCE_TOO_LOW",
                (
                    f"La confiance IA de cette idée est de "
                    f"{cls._humanize_pct(confidence * 100)} alors que ton profil "
                    f"exige au minimum "
                    f"{cls._humanize_pct(_d(profile.min_confidence) * 100)}. "
                    f"Tu peux ajuster « min_confidence » dans ton profil "
                    f"de risque, ou utiliser le bouton « Forcer l'exécution » "
                    f"pour passer outre sous ta responsabilité."
                ),
            )
            if soft is not None:
                return soft

        # ── 5. Stop loss obligatoire mais absent ───────────────────
        if (
                profile.require_stop_loss
                and not is_deriv
                and (stop_loss is None or stop_loss <= 0)
        ):
            soft = _soft_block_or_override(
                "STOP_LOSS_REQUIRED",
                (
                    "Ton profil de risque exige un stop loss sur chaque trade, "
                    "mais cette idée n'en a pas. Définis un stop loss sur "
                    "l'idée, ou retire l'exigence dans ton profil. "
                    "Tu peux aussi forcer l'exécution sous ta responsabilité."
                ),
            )
            if soft is not None:
                return soft
        if is_deriv:
            approved_notional = requested_stake
            approved_quantity = requested_stake
        # ── 6. Nombre max de positions ouvertes ────────────────────
        if (
                profile.max_open_positions
                and profile.max_open_positions > 0
                and open_positions_count >= profile.max_open_positions
        ):
            if not is_demo:
                soft = _soft_block_or_override(
                    "MAX_OPEN_POSITIONS",
                    (
                        f"Tu as déjà {open_positions_count} position(s) "
                        f"ouverte(s) sur les {profile.max_open_positions} "
                        f"autorisé(s) par ton profil de risque. "
                        f"Pour ouvrir un nouveau trade : ferme une position "
                        f"existante, augmente « max_open_positions » dans "
                        f"ton profil, ou clique sur « Forcer l'exécution » "
                        f"pour passer outre cette limite (à ta charge)."
                    ),
                )
                if soft is not None:
                    return soft
            else:
                payload["max_open_positions_warning"] = (
                    f"{open_positions_count}/{profile.max_open_positions} "
                    "positions ouvertes — non bloquant en PAPER/DEMO."
                )

        # ── 7. Perte journalière maximale ──────────────────────────
        if _d(daily_state.total_loss_percent) >= _d(profile.max_daily_loss):
            if profile.kill_switch_enabled:
                cls.trigger_kill_switch(
                    portfolio,
                    profile,
                    "DAILY_LOSS_LIMIT",
                    "Perte journalière maximale atteinte.",
                    payload=payload,
                )
            soft = _soft_block_or_override(
                "DAILY_LOSS_LIMIT",
                (
                    f"La perte du jour ({cls._humanize_pct(daily_state.total_loss_percent)}) "
                    f"a atteint la limite de ton profil "
                    f"({cls._humanize_pct(profile.max_daily_loss)}). "
                    f"Reprends demain, augmente « max_daily_loss » dans ton "
                    f"profil, ou force l'exécution si tu acceptes le risque."
                ),
            )
            if soft is not None:
                return soft

        # ── 8. Perte hebdomadaire maximale ─────────────────────────
        if _d(weekly_state.total_loss_percent) >= _d(profile.max_weekly_loss):
            if not is_demo:
                if profile.kill_switch_enabled:
                    cls.trigger_kill_switch(
                        portfolio,
                        profile,
                        "WEEKLY_LOSS_LIMIT",
                        "Perte hebdomadaire maximale atteinte.",
                        payload=payload,
                    )
                soft = _soft_block_or_override(
                    "WEEKLY_LOSS_LIMIT",
                    (
                        f"La perte de la semaine "
                        f"({cls._humanize_pct(weekly_state.total_loss_percent)}) "
                        f"a atteint la limite "
                        f"({cls._humanize_pct(profile.max_weekly_loss)}). "
                        f"Reprends la semaine prochaine, ajuste ton profil, "
                        f"ou force l'exécution sous ta responsabilité."
                    ),
                )
                if soft is not None:
                    return soft
            else:
                payload["weekly_loss_warning"] = (
                    "Perte hebdomadaire maximale atteinte — non bloquant en PAPER/DEMO."
                )

        # ── 8bis. Perte mensuelle maximale ─────────────────────────
        if _d(monthly_state.total_loss_percent) >= _d(profile.max_monthly_loss):
            if not is_demo:
                if profile.kill_switch_enabled:
                    cls.trigger_kill_switch(
                        portfolio,
                        profile,
                        "MONTHLY_LOSS_LIMIT",
                        "Perte mensuelle maximale atteinte.",
                        payload=payload,
                    )
                soft = _soft_block_or_override(
                    "MONTHLY_LOSS_LIMIT",
                    (
                        f"La perte du mois "
                        f"({cls._humanize_pct(monthly_state.total_loss_percent)}) "
                        f"a atteint la limite "
                        f"({cls._humanize_pct(profile.max_monthly_loss)}). "
                        f"Reprends le mois prochain, ajuste « max_monthly_loss » "
                        f"dans ton profil, ou force l'exécution sous ta responsabilité."
                    ),
                )
                if soft is not None:
                    return soft
            else:
                payload["monthly_loss_warning"] = (
                    "Perte mensuelle maximale atteinte — non bloquant en PAPER/DEMO."
                )

        # ── 9. Drawdown maximal ────────────────────────────────────
        current_drawdown = _d(portfolio.current_drawdown_percent)

        # Une perte/drawdown > 100 % est une anomalie de métrique, pas un vrai signal risk.
        if current_drawdown > Decimal("100"):
            current_drawdown = Decimal("0")

        if current_drawdown >= _d(profile.max_drawdown):
            if not is_demo:
                if profile.kill_switch_enabled:
                    cls.trigger_kill_switch(
                        portfolio,
                        profile,
                        "MAX_DRAWDOWN",
                        "Drawdown maximal atteint.",
                        payload=payload,
                    )
                soft = _soft_block_or_override(
                    "MAX_DRAWDOWN",
                    (
                        f"Le drawdown du portefeuille "
                        f"({cls._humanize_pct(current_drawdown)}) "
                        f"dépasse la limite de ton profil "
                        f"({cls._humanize_pct(profile.max_drawdown)}). "
                        f"Le risque de capitulation est élevé : remets ton "
                        f"capital à flot, élargis ton profil, ou force "
                        f"l'exécution en pleine conscience."
                    ),
                )
                if soft is not None:
                    return soft
            else:
                payload["drawdown_warning"] = (
                    "Drawdown maximal atteint — non bloquant en PAPER/DEMO."
                )

        if _d(profile.max_leverage) > 0 and _d(portfolio.broker_account.mode == "LIVE" and 1 or 1) > _d(
                profile.max_leverage):
            pass

        # ── 9bis. Classe d'instrument (Capital Preservation First) ──
        # ⚠ ORDRE CRITIQUE — ce bloc doit rester APRÈS les blocs 7/8/8bis/9
        # (pertes jour/semaine/mois, drawdown) : ceux-ci déclenchent le kill
        # switch en EFFET DE BORD. Un retour anticipé ici masquerait cette
        # protection, bien plus forte qu'un simple filtrage de classe.
        # Un instrument à espérance négative ou à volatilité élevée n'est pas
        # tradable par défaut : il exige un opt-in explicite, et il est exclu
        # du mode préservation du capital. Blocages SOFT : franchissables via
        # la décharge explicite, ce qui trace l'opt-in dans RiskOverrideAudit.
        from .instruments import InstrumentTier, classify, policy_for_tier

        instrument_tier = classify(asset, symbol=symbol)
        tier_policy = policy_for_tier(instrument_tier)
        payload["instrument_tier"] = instrument_tier
        payload["instrument_tier_max_risk_pct"] = str(tier_policy.max_risk_per_trade_pct)

        if tier_policy.requires_explicit_optin:
            tier_enabled = (
                profile.allow_speculative_instruments
                if instrument_tier == InstrumentTier.SPECULATIVE
                else profile.allow_volatile_instruments
            )
            if not tier_enabled:
                soft = _soft_block_or_override(
                    "INSTRUMENT_TIER_NOT_ENABLED",
                    (
                        f"{symbol} est classé « {tier_policy.label} » et n'est pas "
                        f"autorisé par ton profil. {tier_policy.disclosure} "
                        f"Active explicitement cette classe dans ton profil de "
                        f"risque si tu acceptes ce niveau de risque."
                    ),
                )
                if soft is not None:
                    return soft

        if profile.preservation_mode and not tier_policy.eligible_for_preservation:
            soft = _soft_block_or_override(
                "PRESERVATION_MODE_EXCLUDES_INSTRUMENT",
                (
                    f"Ton profil est en mode « préservation du capital », qui "
                    f"restreint l'univers aux instruments à espérance "
                    f"structurellement non-négative. {symbol} est classé "
                    f"« {tier_policy.label} » et en est exclu. "
                    f"{tier_policy.disclosure}"
                ),
            )
            if soft is not None:
                return soft


        symbol_existing = cls.symbol_open_exposure(portfolio, symbol)
        symbol_future = symbol_existing + approved_notional
        if _d(portfolio.equity) > 0:
            symbol_exposure_pct = (symbol_future / _d(portfolio.equity)) * Decimal("100")
        else:
            symbol_exposure_pct = Decimal("0")

        payload["symbol_exposure_percent"] = str(symbol_exposure_pct)

        if symbol_exposure_pct > _d(profile.max_symbol_exposure_percent):
            reduced_notional = max(
                Decimal("0.00"),
                ((_d(profile.max_symbol_exposure_percent) / Decimal("100")) * _d(portfolio.equity)) - symbol_existing
            )
            if reduced_notional <= 0:
                soft = _soft_block_or_override(
                    "SYMBOL_EXPOSURE_MAX",
                    (
                        f"Tu es déjà exposé à hauteur de "
                        f"{cls._humanize_pct(symbol_exposure_pct)} sur "
                        f"« {symbol} » alors que ton profil limite à "
                        f"{cls._humanize_pct(profile.max_symbol_exposure_percent)}. "
                        f"Réduis ton exposition existante, augmente la limite "
                        f"dans ton profil, ou force l'exécution sous ta "
                        f"responsabilité."
                    ),
                )
                if soft is not None:
                    soft.decision = "REJECT"
                    return soft

            reduced_quantity = reduced_notional / entry_price if entry_price > 0 else Decimal("0")
            return cls._build_result(
                decision="REDUCE",
                approved_stake=reduced_notional,
                approved_quantity=reduced_quantity,
                approved_notional=reduced_notional,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                blocking_reason=(
                    f"Taille réduite automatiquement à "
                    f"{reduced_notional} pour respecter la limite "
                    f"d'exposition « {symbol} » de ton profil."
                ),
                payload=payload,
            )

        asset_class_existing = cls.asset_class_open_exposure(
            portfolio,
            asset_class,
            symbol=symbol,
        )
        asset_class_future = asset_class_existing + approved_notional
        if _d(portfolio.equity) > 0:
            asset_class_pct = (asset_class_future / _d(portfolio.equity)) * Decimal("100")
        else:
            asset_class_pct = Decimal("0")

        payload["asset_class_exposure_percent"] = str(asset_class_pct)

        if asset_class_pct > _d(profile.max_asset_class_exposure_percent):
            if cls.is_paper_or_demo(portfolio):
                payload["asset_class_exposure_warning"] = (
                    f"Exposition classe d'actifs « {asset_class} » à "
                    f"{cls._humanize_pct(asset_class_pct)} (max "
                    f"{cls._humanize_pct(profile.max_asset_class_exposure_percent)}) "
                    "— non bloquant en PAPER/DEMO."
                )
            else:
                reduced_notional = max(
                    Decimal("0.00"),
                    ((_d(profile.max_asset_class_exposure_percent) / Decimal("100")) * _d(
                        portfolio.equity)) - asset_class_existing
                )
                if reduced_notional <= 0:
                    soft = _soft_block_or_override(
                        "ASSET_CLASS_EXPOSURE_MAX",
                        (
                            f"Ta classe d'actifs « {asset_class} » est déjà "
                            f"à {cls._humanize_pct(asset_class_pct)} de ton "
                            f"capital alors que ton profil plafonne à "
                            f"{cls._humanize_pct(profile.max_asset_class_exposure_percent)}. "
                            f"Diversifie sur d'autres classes, augmente la "
                            f"limite, ou force l'exécution si tu acceptes "
                            f"la concentration."
                        ),
                    )
                    if soft is not None:
                        soft.decision = "REJECT"
                        return soft

                reduced_quantity = reduced_notional / entry_price if entry_price > 0 else Decimal("0")
                return cls._build_result(
                    decision="REDUCE",
                    approved_stake=reduced_notional,
                    approved_quantity=reduced_quantity,
                    approved_notional=reduced_notional,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    blocking_reason=(
                        f"Taille réduite automatiquement à {reduced_notional} "
                        f"pour rester sous la limite d'exposition de la "
                        f"classe « {asset_class} »."
                    ),
                    payload=payload,
                )

        if profile.block_on_high_correlation:
            correlated_exposure = cls.correlated_exposure(
                portfolio,
                asset,
                symbol=symbol,
            )
            correlated_future = correlated_exposure + approved_notional
            if _d(portfolio.equity) > 0:
                corr_pct = (correlated_future / _d(portfolio.equity)) * Decimal("100")
            else:
                corr_pct = Decimal("0")

            payload["correlated_exposure_percent"] = str(corr_pct)

            if corr_pct > _d(profile.max_correlated_exposure_percent):
                soft = _soft_block_or_override(
                    "CORRELATED_EXPOSURE_HIGH",
                    (
                        f"Avec ce trade, ton exposition à des actifs "
                        f"fortement corrélés monterait à "
                        f"{cls._humanize_pct(corr_pct)} (max "
                        f"{cls._humanize_pct(profile.max_correlated_exposure_percent)}). "
                        f"Risque de drawdown groupé en cas de retournement. "
                        f"Pense à diversifier ou force l'exécution sous ta "
                        f"responsabilité."
                    ),
                )
                if soft is not None:
                    soft.decision = "REJECT"
                    return soft

        result = cls._build_result(
            decision="APPROVE",
            approved_stake=approved_notional,
            approved_quantity=approved_quantity,
            approved_notional=approved_notional,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            blocking_reason="",
            payload=payload,
        )

        # ── Audit trail override ─────────────────────────────────────────────
        # Si l'utilisateur a explicitement activé risk_override, on persiste
        # un enregistrement immuable quels que soient les codes franchis
        # (même s'il n'y en a aucun — l'intention de passer outre est tracée).
        if risk_override and result.decision == "APPROVE":
            try:
                from risk.models import RiskOverrideAudit

                # Extraire les codes qui ont effectivement été franchis
                applied = payload.get("risk_override", {}).get("applied_to", [])
                codes_bypassed = [e["code"] for e in applied if isinstance(e, dict) and "code" in e]

                # Snapshot léger du profil (valeurs numériques clés seulement)
                profile_snapshot = {
                    "id": profile.id,
                    "name": profile.name,
                    "max_risk_per_trade": str(profile.max_risk_per_trade),
                    "max_daily_loss": str(profile.max_daily_loss),
                    "max_weekly_loss": str(profile.max_weekly_loss),
                    "max_drawdown": str(profile.max_drawdown),
                    "max_open_positions": profile.max_open_positions,
                    "allow_live_trading": profile.allow_live_trading,
                    "allow_short": profile.allow_short,
                    "kill_switch_enabled": profile.kill_switch_enabled,
                }

                RiskOverrideAudit.record(
                    user_id=risk_override_user_id,
                    portfolio=portfolio,
                    symbol=symbol,
                    side=side,
                    requested_stake=requested_stake,
                    codes_bypassed=codes_bypassed,
                    reason=risk_override_reason,
                    ip_address=risk_override_ip or None,
                    user_agent=risk_override_user_agent or "",
                    profile_snapshot=profile_snapshot,
                )
            except Exception as _audit_exc:
                import logging as _log
                _log.getLogger("leotrade.risk.audit").error(
                    "risk_override_audit.hook_failed symbol=%s err=%s",
                    symbol, _audit_exc,
                )

        return result

    @classmethod
    def _build_result(
            cls,
            *,
            decision: str,
            approved_stake: Decimal,
            approved_quantity: Decimal,
            approved_notional: Decimal,
            entry_price: Decimal,
            stop_loss: Optional[Decimal],
            take_profit: Optional[Decimal],
            blocking_reason: str,
            payload: dict,
    ) -> RiskApprovalResult:
        if stop_loss is not None and entry_price > 0 and approved_quantity > 0:
            expected_loss = abs(entry_price - stop_loss) * approved_quantity
        else:
            expected_loss = Decimal("0.00")

        if take_profit is not None and entry_price > 0 and approved_quantity > 0:
            expected_gain = abs(take_profit - entry_price) * approved_quantity
        else:
            expected_gain = Decimal("0.00")

        if expected_loss > 0:
            rr = (expected_gain / expected_loss).quantize(Decimal("0.0001"))
        else:
            rr = Decimal("0.0000")

        return RiskApprovalResult(
            decision=decision,
            approved_stake=approved_stake.quantize(Decimal("0.01")),
            approved_quantity=approved_quantity.quantize(Decimal("0.00000001")),
            approved_notional=approved_notional.quantize(Decimal("0.01")),
            expected_loss=expected_loss.quantize(Decimal("0.01")),
            expected_gain=expected_gain.quantize(Decimal("0.01")),
            risk_reward_ratio=rr,
            blocking_reason=blocking_reason,
            payload=payload,
        )


class RiskDecisionService:
    @staticmethod
    @transaction.atomic
    def persist_decision(
            *,
            portfolio,
            risk_profile,
            symbol: str,
            asset_class: str | None,
            side: str | None,
            requested_stake: Decimal,
            approved_result: RiskApprovalResult,
            requested_quantity: Decimal = Decimal("0"),
            requested_notional: Decimal = Decimal("0.00"),
            signal=None,
            trade_idea=None,
            order=None,
    ) -> RiskDecision:
        return RiskDecision.objects.create(
            portfolio=portfolio,
            risk_profile=risk_profile,
            signal=signal,
            trade_idea=trade_idea,
            order=order,
            symbol=symbol,
            asset_class=asset_class,
            side=side,
            requested_stake=requested_stake,
            approved_stake=approved_result.approved_stake,
            requested_quantity=requested_quantity,
            approved_quantity=approved_result.approved_quantity,
            requested_notional=requested_notional,
            approved_notional=approved_result.approved_notional,
            expected_loss=approved_result.expected_loss,
            expected_gain=approved_result.expected_gain,
            risk_reward_ratio=approved_result.risk_reward_ratio,
            decision=approved_result.decision,
            blocking_reason=approved_result.blocking_reason,
            payload=approved_result.payload,
        )
