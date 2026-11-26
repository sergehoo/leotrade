"""
risk/services_summary.py
========================

État consolidé du Risk Control pour un portefeuille.

L'utilisateur a besoin de savoir, d'un coup d'œil, ce qui le sépare d'un
blocage : combien de perte journalière il lui reste, où en est son
drawdown, combien de positions il peut encore ouvrir. Ces chiffres
existaient tous mais dispersés entre trois services et un gabarit Django.

Le taux d'utilisation est le chiffre utile, pas la limite brute : savoir
que la limite journalière est à 3 % n'apprend rien ; savoir qu'on en a
consommé 80 % change la décision.

Les montants sortent en chaîne (voir portfolio/services_summary.py), les
pourcentages aussi, pour la même raison.
"""

from __future__ import annotations

import logging
from decimal import Decimal

log = logging.getLogger("leotrade.risk.summary")

ZERO = Decimal("0.00")


def _dec(value) -> Decimal:
    try:
        return Decimal(value or 0)
    except Exception:
        return ZERO


def _pct(value) -> str:
    return str(_dec(value).quantize(Decimal("0.01")))


def _usage(consumed: Decimal, limit: Decimal) -> str | None:
    """Part de la limite déjà consommée, en pourcentage.

    `None` quand aucune limite n'est posée : afficher « 0 % utilisé »
    laisserait croire à une protection qui n'existe pas.
    """
    if limit <= 0:
        return None
    return str(((consumed / limit) * Decimal("100")).quantize(Decimal("0.01")))


class RiskSummaryService:

    @staticmethod
    def build(portfolio) -> dict:
        from risk.models import DailyRiskState, KillSwitchEvent, WeeklyRiskState
        from risk.services import RiskGuardService

        profile = RiskGuardService.get_default_profile(portfolio)

        daily = (
            DailyRiskState.objects.filter(portfolio=portfolio)
            .order_by("-day").first()
        )
        weekly = (
            WeeklyRiskState.objects.filter(portfolio=portfolio)
            .order_by("-week_start").first()
        )
        kill_switch = (
            KillSwitchEvent.objects.filter(portfolio=portfolio, is_active=True)
            .order_by("-triggered_at").first()
        )

        open_positions = portfolio.positions.filter(status="OPEN").count()
        max_positions = int(getattr(profile, "max_open_positions", 0) or 0)

        daily_loss = _dec(getattr(daily, "total_loss_percent", ZERO))
        weekly_loss = _dec(getattr(weekly, "total_loss_percent", ZERO))
        drawdown = _dec(portfolio.current_drawdown_percent)

        daily_limit = _dec(getattr(profile, "max_daily_loss", ZERO))
        weekly_limit = _dec(getattr(profile, "max_weekly_loss", ZERO))
        drawdown_limit = _dec(getattr(profile, "max_drawdown", ZERO))

        return {
            "portfolio_id": portfolio.pk,
            "has_profile": profile is not None,
            "profile": RiskSummaryService._profile_payload(profile),

            # Un kill switch actif interdit toute ouverture : c'est
            # l'information la plus importante de cet écran.
            "kill_switch_active": kill_switch is not None,
            "kill_switch_reason": getattr(kill_switch, "reason", "") or "",
            "kill_switch_reason_code": getattr(kill_switch, "reason_code", "") or "",
            "kill_switch_triggered_at": getattr(kill_switch, "triggered_at", None),

            "limits": [
                {
                    "key": "daily_loss",
                    "label": "Perte journalière",
                    "consumed_percent": _pct(daily_loss),
                    "limit_percent": _pct(daily_limit),
                    "usage_percent": _usage(daily_loss, daily_limit),
                },
                {
                    "key": "weekly_loss",
                    "label": "Perte hebdomadaire",
                    "consumed_percent": _pct(weekly_loss),
                    "limit_percent": _pct(weekly_limit),
                    "usage_percent": _usage(weekly_loss, weekly_limit),
                },
                {
                    "key": "drawdown",
                    "label": "Drawdown",
                    "consumed_percent": _pct(drawdown),
                    "limit_percent": _pct(drawdown_limit),
                    "usage_percent": _usage(drawdown, drawdown_limit),
                },
            ],

            "open_positions": open_positions,
            "max_open_positions": max_positions,
            "positions_usage_percent": _usage(
                Decimal(open_positions), Decimal(max_positions),
            ),
        }

    @staticmethod
    def _profile_payload(profile) -> dict | None:
        if profile is None:
            return None
        return {
            "id": profile.pk,
            "name": profile.name,
            "is_active": profile.is_active,
            "max_risk_per_trade": _pct(profile.max_risk_per_trade),
            "max_daily_loss": _pct(profile.max_daily_loss),
            "max_weekly_loss": _pct(profile.max_weekly_loss),
            "max_monthly_loss": _pct(profile.max_monthly_loss),
            "max_drawdown": _pct(profile.max_drawdown),
            "max_open_positions": profile.max_open_positions,
            "max_leverage": _pct(profile.max_leverage),
            "allow_short": profile.allow_short,
            "allow_live_trading": profile.allow_live_trading,
            "require_stop_loss": profile.require_stop_loss,
            "kill_switch_enabled": profile.kill_switch_enabled,
            # Capital Preservation First.
            "preservation_mode": profile.preservation_mode,
            "allow_volatile_instruments": profile.allow_volatile_instruments,
            "allow_speculative_instruments": profile.allow_speculative_instruments,
        }
