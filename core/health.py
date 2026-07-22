from __future__ import annotations

import os
import uuid

from django.conf import settings
from django.core.cache import cache
from django.db import connections
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from core.monitoring import operational_snapshot_age, read_operational_snapshot


def _json_response(payload: dict, *, status: int = 200) -> JsonResponse:
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "no-store, max-age=0"
    return response


@require_GET
def health_live(request):
    return _json_response({
        "status": "ok",
        "service": "leoTrade",
        "kind": "live",
    })


@require_GET
def health_ready(request):
    checks = {
        "database": False,
        "cache": False,
        "monitoring_heartbeat": False,
    }

    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = True
    except Exception:
        pass

    cache_key = f"healthcheck:{os.getpid()}:{uuid.uuid4().hex}"
    try:
        cache.set(cache_key, "ok", timeout=10)
        checks["cache"] = cache.get(cache_key) == "ok"
        cache.delete(cache_key)
    except Exception:
        pass

    snapshot = read_operational_snapshot() if checks["cache"] else None
    snapshot_age = operational_snapshot_age(snapshot)
    heartbeat_max_age = int(
        getattr(settings, "MONITORING_HEARTBEAT_MAX_AGE_SECONDS", 120)
    )
    checks["monitoring_heartbeat"] = (
        snapshot_age is not None and snapshot_age <= heartbeat_max_age
    )
    require_heartbeat = bool(
        getattr(settings, "HEALTH_REQUIRE_MONITORING_HEARTBEAT", not settings.DEBUG)
    )

    ready = checks["database"] and checks["cache"]
    if require_heartbeat:
        ready = ready and checks["monitoring_heartbeat"]

    return _json_response(
        {
            "status": "ok" if ready else "degraded",
            "service": "leoTrade",
            "kind": "ready",
            "checks": checks,
            "monitoring_required": require_heartbeat,
            "operational_status": snapshot.get("status") if snapshot else "unknown",
            "snapshot_age_seconds": snapshot_age,
        },
        status=200 if ready else 503,
    )


@require_GET
def health_diagnostics(request):
    if not request.user.is_authenticated or not request.user.is_staff:
        return _json_response({"detail": "Accès refusé."}, status=403)

    snapshot = read_operational_snapshot()
    return _json_response(
        {
            "status": snapshot.get("status") if snapshot else "unavailable",
            "snapshot_age_seconds": operational_snapshot_age(snapshot),
            "snapshot": snapshot,
        },
        status=200 if snapshot else 503,
    )
