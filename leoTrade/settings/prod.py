from .base import *
from django.core.exceptions import ImproperlyConfigured

DEBUG = False

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
SECURE_SSL_REDIRECT = True

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

# Hardening : interdit JS de lire le cookie CSRF (OWASP).
# Le front doit envoyer le token via le header X-CSRFToken, en lisant
# le {% csrf_token %} injecté dans le HTML, jamais via document.cookie.
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = env("SESSION_COOKIE_AGE", 3600, int)
SESSION_SAVE_EVERY_REQUEST = True
SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"

# Kill switch global — désactive toute soumission d'ordre (ExecutionOrchestrator)
# sans redéployer. Utiliser core.feature_flags.set_trading_enabled(False)
# pour un toggle live via Redis.
FEATURE_TRADING_ENABLED = env("FEATURE_TRADING_ENABLED", False, bool)

if (
    SECRET_KEY == "change-me-in-env"
    or SECRET_KEY.startswith("django-insecure-")
    or len(SECRET_KEY) < 50
    or len(set(SECRET_KEY)) < 5
):
    raise ImproperlyConfigured(
        "SECRET_KEY must be a strong, random value in production."
    )

DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

CACHES["default"] = {
    "BACKEND": "django.core.cache.backends.redis.RedisCache",
    "LOCATION": REDIS_URL,
}

DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}
