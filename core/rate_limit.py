from __future__ import annotations

import time
from django.core.cache import cache
from django.http import JsonResponse


class SimpleRateLimitMiddleware:
    """
    Limite simple sur quelques endpoints sensibles.
    """

    RULES = [
        ("/api/v1/orders/", 60, 60),
        ("/api/v1/brokers/", 60, 60),
        ("/api/v1/recommendations/", 60, 60),
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        user_key = str(request.user.id) if getattr(request, "user", None) and request.user.is_authenticated else request.META.get("REMOTE_ADDR", "anon")

        for prefix, limit, window_seconds in self.RULES:
            if path.startswith(prefix):
                cache_key = f"rl:{prefix}:{user_key}:{int(time.time() // window_seconds)}"
                current = cache.get(cache_key, 0)

                if current >= limit:
                    return JsonResponse(
                        {"detail": "Rate limit exceeded."},
                        status=429,
                    )

                cache.set(cache_key, current + 1, timeout=window_seconds)
                break

        return self.get_response(request)