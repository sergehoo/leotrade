from __future__ import annotations

from django.db import connections
from django.db.utils import OperationalError
from django.http import JsonResponse
from django.core.cache import cache
from django.conf import settings


def health_live(request):
    return JsonResponse({"status": "ok", "service": "leoTrade", "kind": "live"})


def health_ready(request):
    checks = {
        "database": False,
        "cache": False,
    }

    status_code = 200

    try:
        connections["default"].cursor()
        checks["database"] = True
    except OperationalError:
        status_code = 503

    try:
        cache.set("healthcheck", "ok", 5)
        checks["cache"] = cache.get("healthcheck") == "ok"
        if not checks["cache"]:
            status_code = 503
    except Exception:
        status_code = 503

    return JsonResponse({
        "status": "ok" if status_code == 200 else "degraded",
        "checks": checks,
        "env": settings.DEBUG and "dev" or "prod",
    }, status=status_code)