"""
API REST du module Risk Control (DRF).

  GET   /risk/api/profile/                 profil + drawdown + kill switch
  PATCH /risk/api/profile/                 modifier les limites (audit)
  GET   /risk/api/kill-switch/             état kill switch
  POST  /risk/api/kill-switch/activate/    activer (permission ownership)
  POST  /risk/api/kill-switch/deactivate/  désactiver
  GET   /risk/api/states/                  états daily/weekly/monthly
  GET   /risk/api/decisions/               décisions Risk Engine
  POST  /risk/api/emergency/close-position/    fermer 1 position (confirmation)
  POST  /risk/api/emergency/close-all-losing/  fermer les perdantes (confirm. forte)
  POST  /risk/api/emergency/close-all/         fermer tout (DOUBLE confirmation LIVE)

Sécurité : portefeuille résolu et vérifié comme appartenant à request.user.
Mode LIVE : double confirmation exigée (confirm + confirm_live) sur close-all.
"""

from __future__ import annotations

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .services_control import (
    EmergencyPositionService,
    KillSwitchService,
    RiskControlService,
    RiskSettingsUpdateService,
)


def _resolve_portfolio(request):
    """Portefeuille de l'utilisateur : ?portfolio_id=… ou défaut. Ownership strict."""
    from portfolio.models import Portfolio

    qs = Portfolio.objects.filter(user=request.user, is_active=True).select_related("broker_account")
    pid = request.query_params.get("portfolio_id") or request.data.get("portfolio_id")
    if pid:
        try:
            return qs.filter(pk=int(pid)).first()
        except (TypeError, ValueError):
            return None
    return qs.order_by("-is_default", "name").first()


def _mode(portfolio) -> str:
    broker = getattr(portfolio, "broker_account", None)
    return getattr(broker, "mode", "PAPER") or "PAPER"


def _require_portfolio(request):
    portfolio = _resolve_portfolio(request)
    if portfolio is None:
        return None, Response(
            {"ok": False, "message": "Aucun portefeuille actif trouvé."}, status=404,
        )
    return portfolio, None


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def profile(request):
    portfolio, err = _require_portfolio(request)
    if err:
        return err
    if request.method == "PATCH":
        result = RiskSettingsUpdateService.update(
            user=request.user, portfolio=portfolio,
            changes=request.data.get("changes") or request.data,
            request=request,
        )
        return Response(result, status=200 if result.get("ok") else 400)
    return Response(RiskControlService.profile_snapshot(portfolio))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def kill_switch(request):
    portfolio, err = _require_portfolio(request)
    if err:
        return err
    snap = RiskControlService.profile_snapshot(portfolio)
    return Response({
        "portfolio_id": portfolio.id,
        "mode": _mode(portfolio),
        "kill_switch": snap["kill_switch"],
        "events": RiskControlService.kill_switch_events(portfolio),
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def kill_switch_activate(request):
    portfolio, err = _require_portfolio(request)
    if err:
        return err
    result = KillSwitchService.activate(
        user=request.user, portfolio=portfolio,
        reason=request.data.get("reason", ""), request=request,
    )
    return Response(result, status=200 if result.get("ok") else 400)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def kill_switch_deactivate(request):
    portfolio, err = _require_portfolio(request)
    if err:
        return err
    result = KillSwitchService.deactivate(
        user=request.user, portfolio=portfolio,
        reason=request.data.get("reason", ""), request=request,
    )
    return Response(result, status=200 if result.get("ok") else 400)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def states(request):
    portfolio, err = _require_portfolio(request)
    if err:
        return err
    return Response(RiskControlService.states(portfolio))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def decisions(request):
    portfolio, err = _require_portfolio(request)
    if err:
        return err
    return Response({"decisions": RiskControlService.decisions(portfolio)})


# ── Fermetures d'urgence ─────────────────────────────────────────────────────

def _confirmed(request) -> bool:
    return bool(request.data.get("confirm")) is True or request.data.get("confirm") in ("true", "1", 1, True)


def _live_double_ok(request, portfolio) -> tuple[bool, str]:
    """En LIVE, exige confirm ET confirm_live (double confirmation)."""
    if _mode(portfolio) != "LIVE":
        return True, ""
    if not request.data.get("confirm_live"):
        return False, ("⚠ MODE LIVE — argent réel. Double confirmation requise : "
                       "renvoie confirm=true ET confirm_live=true.")
    return True, ""


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def emergency_close_position(request):
    portfolio, err = _require_portfolio(request)
    if err:
        return err
    if not _confirmed(request):
        return Response({"ok": False, "message": "Confirmation requise (confirm=true)."}, status=400)
    ok, msg = _live_double_ok(request, portfolio)
    if not ok:
        return Response({"ok": False, "message": msg, "requires_double_confirmation": True}, status=400)
    position_id = request.data.get("position_id")
    if not position_id:
        return Response({"ok": False, "message": "position_id requis."}, status=400)
    result = EmergencyPositionService.close_position(
        user=request.user, portfolio=portfolio,
        position_id=int(position_id), request=request,
    )
    return Response(result, status=200 if result.get("ok") else 400)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def emergency_close_all_losing(request):
    portfolio, err = _require_portfolio(request)
    if err:
        return err
    if not _confirmed(request):
        return Response({"ok": False, "message": "Confirmation forte requise (confirm=true)."}, status=400)
    ok, msg = _live_double_ok(request, portfolio)
    if not ok:
        return Response({"ok": False, "message": msg, "requires_double_confirmation": True}, status=400)
    result = EmergencyPositionService.close_all_losing(
        user=request.user, portfolio=portfolio, request=request,
    )
    return Response(result, status=200 if result.get("ok") else 400)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def emergency_close_all(request):
    portfolio, err = _require_portfolio(request)
    if err:
        return err
    if not _confirmed(request):
        return Response({"ok": False, "message": "Confirmation requise (confirm=true)."}, status=400)
    # close-all = action maximale → double confirmation TOUJOURS (PAPER ou LIVE)
    if not request.data.get("confirm_double"):
        return Response({
            "ok": False, "requires_double_confirmation": True,
            "message": ("Fermeture de TOUTES les positions : double confirmation requise. "
                        "Renvoie confirm=true ET confirm_double=true."),
        }, status=400)
    ok, msg = _live_double_ok(request, portfolio)
    if not ok:
        return Response({"ok": False, "message": msg, "requires_double_confirmation": True}, status=400)
    result = EmergencyPositionService.close_all(
        user=request.user, portfolio=portfolio, request=request,
    )
    return Response(result, status=200 if result.get("ok") else 400)
