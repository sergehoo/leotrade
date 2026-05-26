import os
from decimal import Decimal
from pathlib import Path

from celery.schedules import crontab
from dotenv import load_dotenv
import logging

# from pythonjsonlogger import jsonlogger

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env(key: str, default=None, cast=str):
    value = os.getenv(key, default)
    if value is None:
        return value
    if cast is bool:
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    if cast is int:
        return int(value)
    if cast is float:
        return float(value)
    if cast is Decimal:
        return Decimal(str(value))
    return cast(value)


def env_list(key: str, default: str = ""):
    raw = os.getenv(key, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


SECRET_KEY = env("SECRET_KEY", "change-me-in-env")
DEBUG = env("DEBUG", False, bool)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "127.0.0.1,localhost")

SITE_ID = env("SITE_ID", 1, int)

INSTALLED_APPS = [
    # IMPORTANT : "daphne" doit être placé AVANT django.contrib.staticfiles
    # pour que `python manage.py runserver` bascule automatiquement sur le
    # serveur ASGI Daphne (qui supporte les WebSocket). Sans ça, runserver
    # est en mode WSGI sync → toutes les connexions /ws/* échouent immédiatement
    # et les clients front bouclent en reconnect infini.
    "daphne",

    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",

    "rest_framework",
    "rest_framework_simplejwt",
    "django_filters",
    "corsheaders",
    "django_celery_beat",
    "django_celery_results",

    "django_otp",
    "django_otp.plugins.otp_static",
    "django_otp.plugins.otp_totp",

    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth_2fa",

    "execution",
    "core",
    "market",
    "brokers",
    "strategies",
    "portfolio",
    "risk",
    "trading",
    "leo_backtesting",
    "dashboard",
    "wallet",
    "api",
    "channels",

    # Phase IA hybride
    "ai_engine",
    # Comptabilité (Wallet ↔ Portfolio transfers)
    "accounting",

    "django_prometheus",
]

MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "core.middleware.RequestIDMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "core.middleware.RequestContextMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "leoTrade.urls"
WSGI_APPLICATION = "leoTrade.wsgi.application"
ASGI_APPLICATION = "leoTrade.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.global_trading_context",
                "core.context_processors.portfolio_context",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": env("DB_ENGINE", "django.db.backends.postgresql"),
        "NAME": env("POSTGRES_DB", "leotrade2"),
        "USER": env("POSTGRES_USER", "postgres"),
        "PASSWORD": env("POSTGRES_PASSWORD", ""),
        "HOST": env("POSTGRES_HOST", "127.0.0.1"),
        "PORT": env("POSTGRES_PORT", "5433"),
        "CONN_MAX_AGE": env("DB_CONN_MAX_AGE", 60, int),
    }
}

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Africa/Abidjan"
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
}

ACCOUNT_AUTHENTICATION_METHOD = "email"
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_LOGIN_ATTEMPTS_LIMIT = 5
ACCOUNT_LOGIN_ATTEMPTS_TIMEOUT = 300
ACCOUNT_SESSION_REMEMBER = False

LOGIN_REDIRECT_URL = "/dashboard/"
ACCOUNT_LOGOUT_REDIRECT_URL = "/accounts/login/"

EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")

ALLAUTH_2FA_ALWAYS_REVEAL_BACKUP_TOKENS = False
ALLAUTH_2FA_SETUP_URL_NAME = "two-factor-setup"

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "")

CACHES = {
    "default": {
        "BACKEND": env("CACHE_BACKEND", "django.core.cache.backends.locmem.LocMemCache"),
        "LOCATION": env("CACHE_LOCATION", "leotrade-cache"),
    }
}

REDIS_URL = env("REDIS_URL", "redis://127.0.0.1:6379/1")
CELERY_BROKER_URL = env("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_BROKER_CONNECTION_RETRY = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 300
CELERY_TASK_SOFT_TIME_LIMIT = 240

# Channel layer config — driven by REDIS_URL so the same setting works in
# dev, docker-compose and prod without forking. Falls back to localhost.
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [
                env("CHANNELS_REDIS_URL", env("REDIS_URL", "redis://127.0.0.1:6379/2"))
            ],
        },
    },
}

STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = env("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", "")

ADYEN_API_KEY = env("ADYEN_API_KEY", "")
ADYEN_MERCHANT_ACCOUNT = env("ADYEN_MERCHANT_ACCOUNT", "")
ADYEN_HMAC_KEY = env("ADYEN_HMAC_KEY", "")
ADYEN_ENV = env("ADYEN_ENV", "TEST")

SITE_BASE_URL = env("SITE_BASE_URL", "http://127.0.0.1:8000")

FERNET_SECRET_KEY = env("FERNET_SECRET_KEY", "")
if not FERNET_SECRET_KEY:
    raise RuntimeError("FERNET_SECRET_KEY manquant dans l'environnement.")

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

CELERY_BEAT_SCHEDULE = {
    "run-autonomous-strategies-every-minute": {
        "task": "strategies.tasks.run_all_autonomous_strategies_task",
        "schedule": crontab(minute="*"),
    },
    "sync-open-deriv-contracts-every-minute": {
        "task": "trading.tasks.sync_open_deriv_contracts_task",
        "schedule": crontab(minute="*"),
    },
    "scan-market-every-1-minute": {
        "task": "trading.tasks.scan_market_1m_task",
        "schedule": crontab(minute="*"),
    },
    "scan-market-every-5-minutes": {
        "task": "trading.tasks.scan_market_5m_task",
        "schedule": crontab(minute="*/5"),
    },
    "expire-trade-ideas-every-minute": {
        "task": "trading.tasks.expire_trade_ideas_task",
        "schedule": crontab(minute="*"),
    },
    "learn-from-trade-ideas-every-5-minutes": {
        "task": "trading.tasks.learn_from_trade_ideas_task",
        "schedule": crontab(minute="*/5"),
    },
    "run-ai-market-cycle-1m": {
        "task": "trading.tasks.run_ai_market_cycle_1m",
        "schedule": crontab(minute="*"),
    },
    "run-ai-market-cycle-5m": {
        "task": "trading.tasks.run_ai_market_cycle_5m",
        "schedule": crontab(minute="*/5"),
    },
    "refresh-portfolio-advice-5m": {
        "task": "trading.tasks.refresh_portfolio_advice",
        "schedule": crontab(minute="*/5"),
    },
    "expire-ai-trade-ideas-1m": {
        "task": "trading.tasks.expire_old_trade_ideas",
        "schedule": crontab(minute="*"),
    },
    "hedge-fund-generation-cycle-5m": {
        "task": "trading.tasks.run_hedge_fund_generation_cycle",
        "schedule": crontab(minute="*/5"),
    },
    "hedge-fund-execution-cycle-5m": {
        "task": "trading.tasks.run_hedge_fund_execution_cycle",
        "schedule": crontab(minute="*/5"),
    },
    "hedge-fund-learning-cycle-15m": {
        "task": "trading.tasks.run_learning_refresh_cycle",
        "schedule": crontab(minute="*/15"),
    },
    "sync-binance-klines-every-5m": {
        "task": "market.tasks.sync_binance_klines",
        "schedule": crontab(minute="*/5"),
    },
    "sync-deriv-candles-every-5m": {
        "task": "market.tasks.sync_deriv_candles",
        "schedule": crontab(minute="*/5"),
    },
    "compute-market-features-every-5m": {
        "task": "market.tasks.compute_market_features_task",
        "schedule": crontab(minute="*/5"),
    },
    "reconcile-all-active-portfolios-every-2-minutes": {
        "task": "execution.tasks.reconcile_all_active_portfolios_task",
        "schedule": crontab(minute="*/2"),
    },
    "refresh-daily-risk-states-every-5-minutes": {
        "task": "risk.tasks.refresh_daily_risk_states_task",
        "schedule": crontab(minute="*/5"),
    },
    "refresh-weekly-risk-states-every-15-minutes": {
        "task": "risk.tasks.refresh_weekly_risk_states_task",
        "schedule": crontab(minute="*/15"),
    },
    # Kill switch enforcement — single canonical entry, every 2 minutes.
    # The duplicated "auto-enforce-kill-switch" entry below has been removed:
    # two beat entries pointing at the same task race each other and inflate
    # Sentry noise.
    "auto-enforce-kill-switch-every-2-minutes": {
        "task": "risk.tasks.auto_enforce_kill_switch_task",
        "schedule": crontab(minute="*/2"),
    },
    "expire-market-opportunities-every-minute": {
        "task": "trading.tasks_ai.expire_market_opportunities_task",
        "schedule": crontab(minute="*"),
    },
    "expire-trade-recommendations-every-minute": {
        "task": "trading.tasks_ai.expire_trade_recommendations_task",
        "schedule": crontab(minute="*"),
    },
    "generate-ai-recommendations-for-all-portfolios-every-5-minutes": {
        "task": "trading.tasks_ai.generate_ai_recommendations_for_all_portfolios_task",
        "schedule": crontab(minute="*/5"),
    },
    "cleanup-old-idempotency-keys-daily": {
        "task": "execution.tasks_maintenance.cleanup_old_idempotency_keys_task",
        "schedule": crontab(hour=3, minute=0),
    },

    # ------------------------------------------------------------------
    # Phase 1 — Sync Deriv réelle (fallback si le streamer WS ne tourne pas)
    # ------------------------------------------------------------------
    # Récupère la balance broker → ajuste via CashLedgerEntry(BROKER_IMPORT)
    "sync-deriv-balance-every-60s": {
        "task": "brokers.tasks_deriv_sync.sync_deriv_balance_task",
        "schedule": crontab(minute="*"),
    },
    # Récupère les contrats ouverts Deriv → maj statut/fill local via
    # brokers.services.deriv_sync.on_open_contract_update (idempotent)
    "sync-deriv-positions-every-60s": {
        "task": "brokers.tasks_deriv_sync.sync_deriv_positions_task",
        "schedule": crontab(minute="*"),
    },

    # ------------------------------------------------------------------
    # AI Engine — avis IA sur les trade ideas ouvertes (Claude/Ollama/Heuristic)
    # ------------------------------------------------------------------
    "advise-open-trade-ideas-every-3m": {
        "task": "ai_engine.tasks.advise_open_trade_ideas_task",
        "schedule": crontab(minute="*/3"),
    },

    # ------------------------------------------------------------------
    # Mark-to-market — refresh Position.current_price depuis le cache Redis
    # (alimenté par les imports candles + ticks broker). Toutes les 15s.
    # ------------------------------------------------------------------
    "update-marks-every-15s": {
        "task": "portfolio.tasks.update_marks_task",
        "schedule": 15.0,
    },
    # Filet de sécurité : broadcast snapshot des positions toutes les 30s
    # (pour rattraper un client qui aurait raté un push live).
    "broadcast-open-positions-every-30s": {
        "task": "portfolio.tasks.broadcast_open_positions_task",
        "schedule": 30.0,
    },
}

SENTRY_DSN = env("SENTRY_DSN", "")
SENTRY_TRACES_SAMPLE_RATE = env("SENTRY_TRACES_SAMPLE_RATE", 0.0, float)
SENTRY_PROFILES_SAMPLE_RATE = env("SENTRY_PROFILES_SAMPLE_RATE", 0.0, float)

# =============================================================================
# AI Engine (Phase IA hybride)
# =============================================================================
# Provider primaire utilisé en premier choix. Si indisponible, on tombe sur le
# secondaire, puis sur le HeuristicProvider (toujours dispo).
#   - "CLAUDE"    : Anthropic API (qualité top, payant, requiert ANTHROPIC_API_KEY)
#   - "OLLAMA"    : LLM local via Ollama (souverain, gratuit, latence locale)
#   - "HEURISTIC" : règles déterministes (toujours dispo, zéro coût, zéro IA)
AI_PRIMARY_PROVIDER = env("AI_PRIMARY_PROVIDER", "CLAUDE")
AI_SECONDARY_PROVIDER = env("AI_SECONDARY_PROVIDER", "OLLAMA")
AI_FORCE_FALLBACK = env("AI_FORCE_FALLBACK", False, bool)

# Anthropic / Claude
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", "")
AI_CLAUDE_MODEL = env("AI_CLAUDE_MODEL", "claude-opus-4-5")

# Ollama
AI_OLLAMA_BASE_URL = env("AI_OLLAMA_BASE_URL", "http://localhost:11434")
AI_OLLAMA_MODEL = env("AI_OLLAMA_MODEL", "llama3")

API_RATE_LIMIT_PER_MINUTE = env("API_RATE_LIMIT_PER_MINUTE", 120, int)
BROKER_RETRY_MAX_ATTEMPTS = env("BROKER_RETRY_MAX_ATTEMPTS", 3, int)
BROKER_RETRY_BACKOFF_SECONDS = env("BROKER_RETRY_BACKOFF_SECONDS", 2, int)

LOG_LEVEL = env("LOG_LEVEL", "INFO")
SENTRY_DSN = env("SENTRY_DSN", "")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_context": {
            "()": "core.logging.RequestContextFilter",
        },
    },
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "fmt": "%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s %(user_id)s",
        },
        "verbose": {
            "format": "[%(asctime)s] %(levelname)s %(name)s %(request_id)s %(user_id)s %(message)s",
        },
    },
    "handlers": {
        "console_json": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["request_context"],
        },
        "console_verbose": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            "filters": ["request_context"],
        },
    },
    "root": {
        "handlers": ["console_json"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["console_json"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "execution": {
            "handlers": ["console_json"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "risk": {
            "handlers": ["console_json"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "trading": {
            "handlers": ["console_json"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "portfolio": {
            "handlers": ["console_json"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}

if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_logging = LoggingIntegration(
        level=logging.INFO,
        event_level=logging.ERROR,
    )

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
            sentry_logging,
        ],
        traces_sample_rate=float(env("SENTRY_TRACES_SAMPLE_RATE", 0.2, float)),
        profiles_sample_rate=float(env("SENTRY_PROFILES_SAMPLE_RATE", 0.0, float)),
        send_default_pii=False,
        environment=env("DJANGO_ENV", "dev"),
    )

# from pathlib import Path
# import os
#
# from celery.schedules import crontab
# from dotenv import load_dotenv
#
# load_dotenv()
#
# BASE_DIR = Path(__file__).resolve().parent.parent.parent
#
# SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
# DEBUG = os.getenv("DEBUG", "False") == "True"
# ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "*").split(",")
#
# INSTALLED_APPS = [
#     "django.contrib.admin",
#     "django.contrib.auth",
#     "django.contrib.contenttypes",
#     "django.contrib.sessions",
#     "django.contrib.messages",
#     "django.contrib.staticfiles",
#     "django.contrib.sites",
#     "rest_framework",
#     "rest_framework_simplejwt",
#     "django_filters",
#     "corsheaders",
#     "django_celery_beat",
#     "django_celery_results",
#     "channels",
#
#     # django-otp AVANT allauth_2fa
#     "django_otp",
#     "django_otp.plugins.otp_static",
#     "django_otp.plugins.otp_totp",
#
#     # allauth
#     "allauth",
#     "allauth.account",
#
#     "allauth.socialaccount",
#     "allauth_2fa",
#
#     "core",
#     "market",
#     "brokers",
#     "strategies",
#     "portfolio",
#     "risk",
#     "trading",
#     "leo_backtesting",
#     "dashboard",
#     'wallet',
# ]
#
# MIDDLEWARE = [
#     "django.middleware.security.SecurityMiddleware",
#     "whitenoise.middleware.WhiteNoiseMiddleware",
#     "corsheaders.middleware.CorsMiddleware",
#     "django.contrib.sessions.middleware.SessionMiddleware",
#     "django.middleware.common.CommonMiddleware",
#     "django.middleware.csrf.CsrfViewMiddleware",
#     "django.contrib.auth.middleware.AuthenticationMiddleware",
#     "django_otp.middleware.OTPMiddleware",
#     "django.contrib.messages.middleware.MessageMiddleware",
#     "django.middleware.clickjacking.XFrameOptionsMiddleware",
#     "allauth.account.middleware.AccountMiddleware",
#     # "allauth_2fa.middleware.AllauthTwoFactorMiddleware",
# ]
#
# ROOT_URLCONF = "leoTrade.urls"
#
# TEMPLATES = [
#     {
#         "BACKEND": "django.template.backends.django.DjangoTemplates",
#         "DIRS": [BASE_DIR / "templates"],
#         "APP_DIRS": True,
#         "OPTIONS": {
#             "context_processors": [
#                 "django.template.context_processors.request",
#                 "django.contrib.auth.context_processors.auth",
#                 "django.contrib.messages.context_processors.messages",
#                 "core.context_processors.global_trading_context",
#                 "core.context_processors.portfolio_context",
#             ]
#         },
#     },
# ]
#
# WSGI_APPLICATION = "leoTrade.wsgi.application"
# ASGI_APPLICATION = "leoTrade.asgi.application"   # ← corrigé
#
# DATABASES = {
#     "default": {
#         "ENGINE": "django.db.backends.postgresql",
#         "NAME": os.getenv("POSTGRES_DB", "leoTrade"),
#         "USER": os.getenv("POSTGRES_USER", "ogah"),
#         "PASSWORD": os.getenv("POSTGRES_PASSWORD", "weddingLIFE18"),
#         "HOST": os.getenv("POSTGRES_HOST", "localhost"),
#         "PORT": os.getenv("POSTGRES_PORT", "5433"),
#     }
# }
#
# SITE_ID = 1
#
# AUTHENTICATION_BACKENDS = [
#     "django.contrib.auth.backends.ModelBackend",
#     "allauth.account.auth_backends.AuthenticationBackend",
# ]
#
# AUTH_PASSWORD_VALIDATORS = []
#
# LANGUAGE_CODE = "fr-fr"
# TIME_ZONE = "Africa/Abidjan"
# USE_I18N = True
# USE_TZ = True
#
#
# STATIC_URL = '/static/'
# STATIC_ROOT = Path(os.environ.get('STATIC_ROOT', BASE_DIR / 'staticfiles'))
# STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []
#
# DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
#
# REST_FRAMEWORK = {
#     "DEFAULT_FILTER_BACKENDS": [
#         "django_filters.rest_framework.DjangoFilterBackend",
#         "rest_framework.filters.SearchFilter",
#         "rest_framework.filters.OrderingFilter",
#     ]
# }
#
# # ── Allauth ───────────────────────────────────────────────
# ACCOUNT_AUTHENTICATION_METHOD = "email"
# ACCOUNT_EMAIL_REQUIRED = True
# ACCOUNT_EMAIL_VERIFICATION = "mandatory"
# ACCOUNT_USERNAME_REQUIRED = False
# ACCOUNT_LOGIN_ATTEMPTS_LIMIT = 5
# ACCOUNT_LOGIN_ATTEMPTS_TIMEOUT = 300
# ACCOUNT_SESSION_REMEMBER = False
# ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE = True
# ACCOUNT_UNIQUE_EMAIL = True
# ACCOUNT_SIGNUP_PASSWORD_ENTER_TWICE = True
#
# LOGIN_REDIRECT_URL = "/dashboard/"
# ACCOUNT_LOGOUT_REDIRECT_URL = "/accounts/login/"
#
# EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
#
# # ── 2FA ───────────────────────────────────────────────────
# ALLAUTH_2FA_ALWAYS_REVEAL_BACKUP_TOKENS = False
# ALLAUTH_2FA_SETUP_URL_NAME = "two-factor-setup"
#
# STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
# STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
# STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
#
# ADYEN_API_KEY = os.getenv("ADYEN_API_KEY", "")
# ADYEN_MERCHANT_ACCOUNT = os.getenv("ADYEN_MERCHANT_ACCOUNT", "")
# ADYEN_HMAC_KEY = os.getenv("ADYEN_HMAC_KEY", "")
# ADYEN_ENV = os.getenv("ADYEN_ENV", "TEST")  # TEST or LIVE
#
# SITE_BASE_URL = os.getenv("SITE_BASE_URL", "http://127.0.0.1:8000")
#
#
# CACHES = {
#     "default": {
#         "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
#         "LOCATION": "leotrade-cache",
#     }
# }
# CELERY_BROKER_CONNECTION_RETRY = True
# CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
#
# CELERY_BEAT_SCHEDULE = {
#     "run-autonomous-strategies-every-minute": {
#         "task": "strategies.tasks.run_all_autonomous_strategies_task",
#         "schedule": crontab(minute="*"),
#     },
#     "sync-open-deriv-contracts-every-minute": {
#         "task": "trading.tasks.sync_open_deriv_contracts_task",
#         "schedule": crontab(minute="*"),
#     },
#     "scan-market-every-1-minute": {
#         "task": "trading.tasks.scan_market_1m_task",
#         "schedule": crontab(minute="*"),
#     },
#     "scan-market-every-5-minutes": {
#         "task": "trading.tasks.scan_market_5m_task",
#         "schedule": crontab(minute="*/5"),
#     },
#     "expire-trade-ideas-every-minute": {
#         "task": "trading.tasks.expire_trade_ideas_task",
#         "schedule": crontab(minute="*"),
#     },
#     "learn-from-trade-ideas-every-5-minutes": {
#         "task": "trading.tasks.learn_from_trade_ideas_task",
#         "schedule": crontab(minute="*/5"),
#     },
#     "run-ai-market-cycle-1m": {
#         "task": "trading.tasks.run_ai_market_cycle_1m",
#         "schedule": crontab(minute="*"),
#     },
#     "run-ai-market-cycle-5m": {
#         "task": "trading.tasks.run_ai_market_cycle_5m",
#         "schedule": crontab(minute="*/5"),
#     },
#     "refresh-portfolio-advice-5m": {
#         "task": "trading.tasks.refresh_portfolio_advice",
#         "schedule": crontab(minute="*/5"),
#     },
#     "expire-ai-trade-ideas-1m": {
#         "task": "trading.tasks.expire_old_trade_ideas",
#         "schedule": crontab(minute="*"),
#     },
# }
#
# CELERY_BEAT_SCHEDULE.update({
#     "hedge-fund-generation-cycle-5m": {
#         "task": "trading.tasks.run_hedge_fund_generation_cycle",
#         "schedule": crontab(minute="*/5"),
#     },
#     "hedge-fund-execution-cycle-5m": {
#         "task": "trading.tasks.run_hedge_fund_execution_cycle",
#         "schedule": crontab(minute="*/5"),
#     },
#     "hedge-fund-learning-cycle-15m": {
#         "task": "trading.tasks.run_learning_refresh_cycle",
#         "schedule": crontab(minute="*/15"),
#     },
# })
#
# CELERY_BEAT_SCHEDULE.update({
#     "sync-binance-klines-every-5m": {
#         "task": "market.tasks.sync_binance_klines",
#         "schedule": crontab(minute="*/5"),
#     },
#     "sync-deriv-candles-every-5m": {
#         "task": "market.tasks.sync_deriv_candles",
#         "schedule": crontab(minute="*/5"),
#     },
#     "compute-market-features-every-5m": {
#         "task": "market.tasks.compute_market_features_task",
#         "schedule": crontab(minute="*/5"),
#     },
# })
