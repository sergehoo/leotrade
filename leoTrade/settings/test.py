"""
leoTrade/settings/test.py
==========================

Settings minimalistes pour la suite pytest.

Différences avec dev :
- Utilise SQLite en mémoire → pas de Postgres nécessaire pour `pytest`
- Désactive Redis / Channels (pas de WebSocket dans les tests)
- Désactive daphne (pas de ASGI dans les tests)
- Désactive Celery (les tâches sont mockées dans les tests)
- FEATURE_TRADING_ENABLED = True par défaut (les tests qui en ont besoin
  le surchargent via `settings.FEATURE_TRADING_ENABLED = False`)
"""

from .base import *  # noqa: F401, F403

DEBUG = True

# ── Base de données : SQLite en mémoire ──────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "TEST": {
            "NAME": ":memory:",
        },
    }
}

# ── Apps : retirer daphne (nécessite ASGI) ───────────────────────────────────
INSTALLED_APPS = [app for app in INSTALLED_APPS if app != "daphne"]  # noqa: F405

# ── Channels : backend local (pas de Redis) ──────────────────────────────────
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

# ── Cache : local memory (pas de Redis) ─────────────────────────────────────
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# ── Email : console ──────────────────────────────────────────────────────────
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# ── Celery : exécution synchrone dans les tests ─────────────────────────────
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# ── Sécurité : clé statique pour les tests ──────────────────────────────────
SECRET_KEY = "test-secret-key-not-for-production-lyneci"

# ── Staticfiles : pas de manifest ───────────────────────────────────────────
STORAGES["staticfiles"] = {
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
}

# ── Logging : silencieux pendant les tests ───────────────────────────────────
import logging
logging.disable(logging.CRITICAL)

# ── Kill switch global : activé par défaut ───────────────────────────────────
FEATURE_TRADING_ENABLED = True
HEALTH_REQUIRE_MONITORING_HEARTBEAT = False

# ── Allauth : URL de login ───────────────────────────────────────────────────
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

# ── Sites framework : ID requis par allauth ──────────────────────────────────
SITE_ID = 1
