from __future__ import annotations

from urllib.parse import urlparse

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.checks import Error, Tags, Warning, register


def _error(message, hint, check_id):
    return Error(message, hint=hint, id=check_id)


def _is_placeholder(value):
    return str(value or "").strip().upper().startswith("REPLACE_")


@register(Tags.security, deploy=True)
def production_configuration_checks(app_configs, **kwargs):
    errors = []

    if settings.DEBUG:
        errors.append(_error("DEBUG est actif.", "Définir DEBUG=False.", "lyneci.E001"))

    allowed_hosts = {str(host).strip() for host in settings.ALLOWED_HOSTS}
    if not allowed_hosts or "*" in allowed_hosts:
        errors.append(_error(
            "ALLOWED_HOSTS est vide ou contient un wildcard.",
            "Déclarer explicitement le domaine public.",
            "lyneci.E002",
        ))

    site_base_url = str(getattr(settings, "SITE_BASE_URL", "") or "")
    parsed_site = urlparse(site_base_url)
    if parsed_site.scheme != "https" or not parsed_site.netloc:
        errors.append(_error(
            "SITE_BASE_URL n'est pas une URL HTTPS valide.",
            "Utiliser l'URL publique complète, par exemple https://lyneci.com.",
            "lyneci.E003",
        ))

    trusted_origins = {str(origin).rstrip("/") for origin in settings.CSRF_TRUSTED_ORIGINS}
    if site_base_url.rstrip("/") not in trusted_origins:
        errors.append(_error(
            "L'origine publique manque dans CSRF_TRUSTED_ORIGINS.",
            "Ajouter SITE_BASE_URL à CSRF_TRUSTED_ORIGINS.",
            "lyneci.E004",
        ))

    traefik_app_host = str(getattr(settings, "TRAEFIK_APP_HOST", "") or "").strip().lower()
    if traefik_app_host:
        traefik_origin = f"https://{traefik_app_host}"
        if traefik_app_host not in allowed_hosts:
            errors.append(_error(
                "Le domaine Traefik manque dans ALLOWED_HOSTS.",
                "Ajouter TRAEFIK_APP_HOST à ALLOWED_HOSTS.",
                "lyneci.E012",
            ))
        if traefik_origin not in trusted_origins:
            errors.append(_error(
                "L'origine Traefik manque dans CSRF_TRUSTED_ORIGINS.",
                f"Ajouter {traefik_origin} à CSRF_TRUSTED_ORIGINS.",
                "lyneci.E013",
            ))
        if parsed_site.hostname != traefik_app_host:
            errors.append(_error(
                "SITE_BASE_URL et TRAEFIK_APP_HOST utilisent des domaines différents.",
                "Configurer le même domaine public dans les deux variables.",
                "lyneci.E014",
            ))

    if settings.EMAIL_BACKEND.endswith("console.EmailBackend"):
        errors.append(_error(
            "Le backend email console est interdit en production.",
            "Configurer le backend SMTP et ses identifiants.",
            "lyneci.E005",
        ))

    smtp_values = {
        "EMAIL_HOST": getattr(settings, "EMAIL_HOST", ""),
        "EMAIL_HOST_USER": getattr(settings, "EMAIL_HOST_USER", ""),
        "EMAIL_HOST_PASSWORD": getattr(settings, "EMAIL_HOST_PASSWORD", ""),
        "DEFAULT_FROM_EMAIL": getattr(settings, "DEFAULT_FROM_EMAIL", ""),
    }
    invalid_smtp_values = [
        key
        for key, value in smtp_values.items()
        if _is_placeholder(value) or (key in {"EMAIL_HOST", "DEFAULT_FROM_EMAIL"} and not value)
    ]
    if invalid_smtp_values:
        errors.append(_error(
            "La configuration SMTP est absente ou contient des placeholders.",
            f"Configurer les variables suivantes : {', '.join(invalid_smtp_values)}.",
            "lyneci.E015",
        ))

    if settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL:
        errors.append(_error(
            "EMAIL_USE_TLS et EMAIL_USE_SSL sont actifs simultanément.",
            "Activer uniquement le mode attendu par le fournisseur SMTP.",
            "lyneci.E016",
        ))

    if getattr(settings, "ACCOUNT_EMAIL_VERIFICATION", "") != "mandatory":
        errors.append(_error(
            "La vérification email n'est pas obligatoire.",
            "Définir ACCOUNT_EMAIL_VERIFICATION='mandatory' en production.",
            "lyneci.E017",
        ))

    if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
        errors.append(_error(
            "La base de production n'est pas PostgreSQL.",
            "Configurer DB_ENGINE=django.db.backends.postgresql.",
            "lyneci.E006",
        ))

    cache_backend = settings.CACHES["default"]["BACKEND"]
    if "redis" not in cache_backend.lower():
        errors.append(_error(
            "Le cache partagé de production n'est pas Redis.",
            "Utiliser django.core.cache.backends.redis.RedisCache.",
            "lyneci.E007",
        ))

    redis_url = urlparse(str(getattr(settings, "REDIS_URL", "")))
    if redis_url.scheme not in {"redis", "rediss"} or not redis_url.password:
        errors.append(_error(
            "Redis n'est pas protégé par authentification.",
            "Configurer REDIS_URL avec un mot de passe dédié.",
            "lyneci.E011",
        ))

    try:
        Fernet(str(settings.FERNET_SECRET_KEY).encode("ascii"))
    except Exception:
        errors.append(_error(
            "FERNET_SECRET_KEY est invalide.",
            "Générer une clé Fernet et la conserver durablement.",
            "lyneci.E008",
        ))

    if not getattr(settings, "METRICS_AUTH_TOKEN", ""):
        errors.append(_error(
            "METRICS_AUTH_TOKEN est absent.",
            "Définir un token aléatoire pour protéger /metrics.",
            "lyneci.E009",
        ))

    if getattr(settings, "PAYMENT_DEFAULT_PROVIDER", "") == "PAYSTACK":
        if not (
            getattr(settings, "PAYSTACK_SECRET_KEY", "")
            and getattr(settings, "PAYSTACK_PUBLIC_KEY", "")
        ):
            errors.append(_error(
                "Paystack est le provider par défaut mais ses clés sont absentes.",
                "Définir PAYSTACK_SECRET_KEY et PAYSTACK_PUBLIC_KEY.",
                "lyneci.E010",
            ))

    primary_ai = getattr(settings, "AI_PRIMARY_PROVIDER", "").upper()
    ai_key_names = {
        "DEEPSEEK": "DEEPSEEK_API_KEY",
        "CLAUDE": "ANTHROPIC_API_KEY",
    }
    required_ai_key = ai_key_names.get(primary_ai)
    if required_ai_key and not getattr(settings, required_ai_key, ""):
        errors.append(Warning(
            f"Le provider IA principal {primary_ai} n'a pas de clé API.",
            hint=f"Définir {required_ai_key} ou choisir HEURISTIC/OLLAMA.",
            id="lyneci.W003",
        ))

    if getattr(settings, "FEATURE_TRADING_ENABLED", False):
        errors.append(Warning(
            "Le trading live est actif pendant le contrôle de déploiement.",
            hint="Déployer d'abord avec FEATURE_TRADING_ENABLED=False puis activer après validation.",
            id="lyneci.W001",
        ))

    if not getattr(settings, "SENTRY_DSN", ""):
        errors.append(Warning(
            "SENTRY_DSN n'est pas configuré.",
            hint="Configurer un collecteur d'erreurs avant ouverture publique.",
            id="lyneci.W002",
        ))

    return errors
