from __future__ import annotations

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.core.cache import cache
import redis


def health_live(request):
    return JsonResponse({"status": "ok", "service": "leoTrade", "check": "live"}, status=200)


def health_ready(request):
    checks = {
        "database": False,
        "cache": False,
        "redis": False,
    }

    errors = {}

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = True
    except Exception as exc:
        errors["database"] = str(exc)

    try:
        cache.set("healthcheck", "ok", timeout=10)
        checks["cache"] = cache.get("healthcheck") == "ok"
    except Exception as exc:
        errors["cache"] = str(exc)

    try:
        r = redis.from_url(settings.REDIS_URL)
        checks["redis"] = bool(r.ping())
    except Exception as exc:
        errors["redis"] = str(exc)

    ok = all(checks.values())

    return JsonResponse(
        {
            "status": "ok" if ok else "degraded",
            "checks": checks,
            "errors": errors,
        },
        status=200 if ok else 503,
    )