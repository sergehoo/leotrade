"""
Module Risk Control — services réels accessibles via /risk/.

Tous les services respectent les contraintes du cahier des charges :
  - aucune action broker directe (les fermetures passent par
    ExecutionOrchestrator → ordre opposé),
  - vérification broker actif + portefeuille + positions ouvertes,
  - journalisation systématique (RiskAuditLog),
  - notification email + in-app,
  - mode PAPER/LIVE explicite, double confirmation côté API pour le LIVE,
  - aucune donnée fictive (tout vient de la base réelle).

Services :
  - RiskControlService        : lectures (profil, drawdown, états, décisions)
  - KillSwitchService         : activation/désactivation manuelle + audit
  - RiskSettingsUpdateService : modification auditée des limites
  - EmergencyPositionService  : fermetures d'urgence (1 / perdantes / toutes)
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import RiskAuditLog

log = logging.getLogger("leotrade.risk.control")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _d(value, default="0") -> Decimal:
    try:
        return Decimal(str(value if value is not None else default))
    except Exception:
        return Decimal(default)


def _portfolio_mode(portfolio) -> str:
    broker = getattr(portfolio, "broker_account", None)
    return getattr(broker, "mode", "PAPER") or "PAPER"


def _audit(*, user, portfolio, action, summary, mode="PAPER", before=None,
           after=None, payload=None, success=True, error="", request=None):
    ip, ua = None, ""
    if request is not None:
        ip = request.META.get("REMOTE_ADDR")
        ua = (request.META.get("HTTP_USER_AGENT") or "")[:300]
    try:
        return RiskAuditLog.objects.create(
            user=user, portfolio=portfolio, action=action, mode=mode,
            summary=summary[:2000], before=before or {}, after=after or {},
            payload=payload or {}, success=success, error_message=error[:2000],
            ip_address=ip, user_agent=ua,
        )
    except Exception:
        log.exception("risk.audit_failed action=%s portfolio=%s", action,
                      getattr(portfolio, "id", None))
        return None


def _notify(user, event_type, title, message, payload=None):
    try:
        from notifications.shortcuts import notify
        notify(user, event_type, title=title, message=message, payload=payload or {})
    except Exception:
        log.exception("risk.notify_failed event=%s", event_type)


# ── Lectures ──────────────────────────────────────────────────────────────────

class RiskControlService:
    @staticmethod
    def profile_snapshot(portfolio) -> dict:
        from .services import RiskGuardService, RiskStateService

        profile = RiskGuardService.get_default_profile(portfolio)
        daily = RiskStateService.refresh_daily_state(portfolio)
        weekly = RiskStateService.refresh_weekly_state(portfolio)
        monthly = RiskStateService.refresh_monthly_state(portfolio)
        ks_active = RiskGuardService.has_active_kill_switch(portfolio)

        return {
            "portfolio": {
                "id": portfolio.id,
                "name": portfolio.name,
                "mode": _portfolio_mode(portfolio),
                "equity": str(portfolio.equity),
                "balance": str(portfolio.current_balance),
                "available_cash": str(portfolio.available_cash),
            },
            "profile": {
                "id": profile.id,
                "name": profile.name,
                "max_risk_per_trade": str(profile.max_risk_per_trade),
                "max_daily_loss": str(profile.max_daily_loss),
                "max_weekly_loss": str(profile.max_weekly_loss),
                "max_monthly_loss": str(profile.max_monthly_loss),
                "max_drawdown": str(profile.max_drawdown),
                "max_open_positions": profile.max_open_positions,
                "allow_live_trading": profile.allow_live_trading,
                "kill_switch_enabled": profile.kill_switch_enabled,
            },
            "drawdown": {
                "current_percent": float(portfolio.current_drawdown_percent or 0),
                "max_percent": float(portfolio.max_drawdown_percent or 0),
                "daily_loss_percent": str(daily.total_loss_percent),
                "weekly_loss_percent": str(weekly.total_loss_percent),
                "monthly_loss_percent": str(monthly.total_loss_percent),
            },
            "kill_switch": {
                "active": ks_active,
                "enabled": profile.kill_switch_enabled,
            },
        }

    @staticmethod
    def states(portfolio, limit: int = 30) -> dict:
        return {
            "daily": list(
                portfolio.daily_risk_states.order_by("-day")[:limit].values(
                    "day", "total_loss_percent", "total_loss_amount",
                    "equity_open", "equity_current", "open_positions_count",
                    "kill_switch_triggered",
                )
            ),
            "weekly": list(
                portfolio.weekly_risk_states.order_by("-week_start")[:limit].values(
                    "week_start", "total_loss_percent", "equity_open",
                    "equity_current", "kill_switch_triggered",
                )
            ),
            "monthly": list(
                portfolio.monthly_risk_states.order_by("-month_start")[:limit].values(
                    "month_start", "total_loss_percent", "equity_open",
                    "equity_current", "kill_switch_triggered",
                )
            ),
        }

    @staticmethod
    def decisions(portfolio, limit: int = 50) -> list[dict]:
        from .models import RiskDecision

        qs = (
            RiskDecision.objects.filter(portfolio=portfolio)
            .order_by("-created_at")[:limit]
        )
        return [
            {
                "id": d.id,
                "symbol": d.symbol,
                "side": d.side,
                "decision": d.decision,
                "blocking_reason": d.blocking_reason,
                "requested_stake": str(d.requested_stake),
                "approved_stake": str(d.approved_stake),
                "risk_reward_ratio": str(d.risk_reward_ratio),
                "created_at": d.created_at.isoformat(),
            }
            for d in qs
        ]

    @staticmethod
    def kill_switch_events(portfolio, limit: int = 20) -> list[dict]:
        return list(
            portfolio.kill_switch_events.order_by("-triggered_at")[:limit].values(
                "id", "reason_code", "reason", "is_active",
                "triggered_at", "resolved_at",
            )
        )


# ── Kill switch ────────────────────────────────────────────────────────────────

class KillSwitchService:
    @classmethod
    @transaction.atomic
    def activate(cls, *, user, portfolio, reason: str = "", request=None) -> dict:
        from .services import RiskGuardService

        if RiskGuardService.has_active_kill_switch(portfolio):
            return {"ok": True, "already_active": True,
                    "message": f"Le kill switch est déjà actif sur « {portfolio.name} »."}

        profile = RiskGuardService.get_default_profile(portfolio)
        RiskGuardService.trigger_kill_switch(
            portfolio, profile, "MANUAL",
            reason or "Kill switch activé manuellement depuis le module Risk Control.",
        )
        mode = _portfolio_mode(portfolio)
        _audit(user=user, portfolio=portfolio, action="KILL_SWITCH_ACTIVATE",
               mode=mode, summary=reason or "Activation manuelle", request=request,
               payload={"reason": reason})
        # La notification KILL_SWITCH_ACTIVATED est déjà émise par trigger_kill_switch.
        return {"ok": True, "already_active": False,
                "message": f"🛑 Kill switch ACTIVÉ sur « {portfolio.name} » — "
                           f"aucune nouvelle entrée ne sera exécutée."}

    @classmethod
    @transaction.atomic
    def deactivate(cls, *, user, portfolio, reason: str = "", request=None) -> dict:
        from .services import RiskGuardService

        if not RiskGuardService.has_active_kill_switch(portfolio):
            return {"ok": True, "already_inactive": True,
                    "message": f"Aucun kill switch actif sur « {portfolio.name} »."}

        RiskGuardService.resolve_kill_switch(portfolio)
        mode = _portfolio_mode(portfolio)
        _audit(user=user, portfolio=portfolio, action="KILL_SWITCH_DEACTIVATE",
               mode=mode, summary=reason or "Désactivation manuelle", request=request,
               payload={"reason": reason})
        return {"ok": True, "already_inactive": False,
                "message": f"Kill switch levé sur « {portfolio.name} » — le trading peut reprendre."}


# ── Modification des limites ────────────────────────────────────────────────────

class RiskSettingsUpdateService:
    EDITABLE_FIELDS = {
        "max_risk_per_trade", "max_daily_loss", "max_weekly_loss",
        "max_monthly_loss", "max_drawdown", "max_open_positions",
        "max_leverage", "min_confidence", "allow_short",
        "require_stop_loss", "kill_switch_enabled",
    }
    DECIMAL_FIELDS = {
        "max_risk_per_trade", "max_daily_loss", "max_weekly_loss",
        "max_monthly_loss", "max_drawdown", "max_leverage", "min_confidence",
    }

    @classmethod
    @transaction.atomic
    def update(cls, *, user, portfolio, changes: dict, request=None) -> dict:
        from .services import RiskGuardService

        profile = RiskGuardService.get_default_profile(portfolio)
        before, after, applied = {}, {}, {}

        for field, raw in (changes or {}).items():
            if field not in cls.EDITABLE_FIELDS:
                continue
            old = getattr(profile, field)
            try:
                if field in cls.DECIMAL_FIELDS:
                    new = _d(raw)
                    if new < 0:
                        return {"ok": False, "message": f"{field} ne peut pas être négatif."}
                elif field == "max_open_positions":
                    new = max(0, int(raw))
                else:
                    new = bool(raw)
            except Exception:
                return {"ok": False, "message": f"Valeur invalide pour {field}."}

            if old != new:
                before[field] = str(old)
                after[field] = str(new)
                setattr(profile, field, new)
                applied[field] = new

        if not applied:
            return {"ok": True, "message": "Aucune modification à appliquer.",
                    "applied": {}}

        profile.save(update_fields=list(applied.keys()) + ["updated_at"])
        mode = _portfolio_mode(portfolio)
        _audit(user=user, portfolio=portfolio, action="RISK_SETTINGS_UPDATE",
               mode=mode, summary=f"Modification de {len(applied)} limite(s) de risque.",
               before=before, after=after, request=request)
        _notify(
            user, "SECURITY_ALERT",
            title=f"Limites de risque modifiées — {portfolio.name}",
            message=(
                f"{len(applied)} limite(s) de risque modifiée(s) : "
                + ", ".join(f"{k}={v}" for k, v in after.items())
            ),
            payload={"portfolio_id": portfolio.id, "changes": after},
        )
        return {"ok": True, "message": "Limites mises à jour.", "applied": after}


# ── Fermetures d'urgence ────────────────────────────────────────────────────────

class EmergencyPositionService:
    """Fermetures via ordre OPPOSÉ soumis à ExecutionOrchestrator. Jamais
    d'appel broker direct. Vérifie broker actif + positions ouvertes."""

    @staticmethod
    def _open_positions(portfolio):
        return (
            portfolio.positions
            .filter(status__in=["OPEN", "PARTIALLY_CLOSED"])
            .select_related("broker_account", "asset")
        )

    @classmethod
    def _close_one(cls, position, fraction: Decimal, request_user, *, source_action) -> dict:
        from execution.services import ExecutionOrchestrator

        broker = position.broker_account
        if broker is None or not broker.is_active:
            return {"ok": False, "position_id": position.id,
                    "message": "Broker inactif — fermeture impossible."}

        qty = (_d(position.quantity) * fraction).quantize(Decimal("0.00000001"))
        if qty <= 0:
            return {"ok": False, "position_id": position.id, "message": "Quantité nulle."}

        price = _d(position.current_price) or _d(position.average_entry_price)
        side = "SELL" if position.side == "LONG" else "BUY"
        notional = (qty * price).quantize(Decimal("0.01"))
        order = ExecutionOrchestrator.create_order(
            user=position.portfolio.user,
            portfolio=position.portfolio,
            broker_account=broker,
            symbol=position.symbol,
            side=side,
            approved_quantity=qty,
            requested_stake_amount=notional,
            approved_notional=notional,
            requested_price=price,
            asset=position.asset,
            source="AI_ASSISTED",
            metadata={"closes_position_id": position.id,
                      "close_fraction": str(fraction),
                      "emergency_action": source_action},
        )
        submitted = ExecutionOrchestrator.submit_order(order)
        return {"ok": True, "position_id": position.id, "order_id": submitted.id,
                "symbol": position.symbol, "status": submitted.status,
                "quantity": str(qty)}

    @classmethod
    @transaction.atomic
    def close_position(cls, *, user, portfolio, position_id: int, request=None) -> dict:
        position = cls._open_positions(portfolio).filter(pk=position_id).first()
        if position is None:
            return {"ok": False, "message": "Position introuvable ou déjà fermée."}
        result = cls._close_one(position, Decimal("1"), user, source_action="EMERGENCY_CLOSE_POSITION")
        mode = _portfolio_mode(portfolio)
        _audit(user=user, portfolio=portfolio, action="EMERGENCY_CLOSE_POSITION",
               mode=mode, summary=f"Fermeture {position.symbol} (#{position.id}).",
               payload=result, success=result.get("ok", False),
               error="" if result.get("ok") else result.get("message", ""),
               request=request)
        if result.get("ok"):
            _notify(user, "POSITION_CLOSED",
                    title=f"Fermeture d'urgence : {position.symbol}",
                    message=f"Ordre de clôture soumis sur {position.symbol} "
                            f"(statut {result.get('status')}).",
                    payload={"portfolio_id": portfolio.id, **result})
        return {"ok": result.get("ok", False), "message": result.get("message", "Ordre de clôture soumis."),
                "results": [result]}

    @classmethod
    @transaction.atomic
    def close_all_losing(cls, *, user, portfolio, request=None) -> dict:
        losing = [p for p in cls._open_positions(portfolio) if _d(p.unrealized_pnl) < 0]
        return cls._close_batch(
            user=user, portfolio=portfolio, positions=losing,
            action="EMERGENCY_CLOSE_LOSING",
            label="positions perdantes", request=request,
        )

    @classmethod
    @transaction.atomic
    def close_all(cls, *, user, portfolio, request=None) -> dict:
        positions = list(cls._open_positions(portfolio))
        return cls._close_batch(
            user=user, portfolio=portfolio, positions=positions,
            action="EMERGENCY_CLOSE_ALL",
            label="toutes les positions", request=request,
        )

    @classmethod
    def _close_batch(cls, *, user, portfolio, positions, action, label, request) -> dict:
        if not positions:
            return {"ok": True, "message": f"Aucune position à fermer ({label}).",
                    "results": []}
        results = [
            cls._close_one(p, Decimal("1"), user, source_action=action)
            for p in positions
        ]
        ok_count = sum(1 for r in results if r.get("ok"))
        mode = _portfolio_mode(portfolio)
        _audit(user=user, portfolio=portfolio, action=action, mode=mode,
               summary=f"Fermeture {label} : {ok_count}/{len(results)} ordre(s) soumis.",
               payload={"results": results}, success=ok_count > 0, request=request)
        _notify(user, "POSITION_CLOSED",
                title=f"Fermeture d'urgence — {label}",
                message=f"{ok_count}/{len(results)} ordre(s) de clôture soumis sur « {portfolio.name} ».",
                payload={"portfolio_id": portfolio.id, "closed": ok_count, "total": len(results)})
        return {"ok": ok_count > 0,
                "message": f"{ok_count}/{len(results)} ordre(s) de clôture soumis ({label}).",
                "results": results}
