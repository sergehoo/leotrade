from .base import *

DEBUG = True

# Restreint même en dev — pour empêcher qu'un déploiement accidentel
# avec le settings dev expose un Host Header Injection. Si tu travailles
# avec ngrok, ajoute le domaine dans la liste.
ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "*.ngrok.io",
    "*.ngrok-free.app",
    "*.localhost",
]

# Kill switch local — peut être surchargé par variable d'env
# FEATURE_TRADING_ENABLED = env.bool("FEATURE_TRADING_ENABLED", default=True)

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

CACHES["default"] = {
    "BACKEND": "django.core.cache.backends.redis.RedisCache",
    "LOCATION": REDIS_URL,
}

# IMPORTANT — override de STATICFILES_STORAGE en DEV.
# En base.py, on a `whitenoise.storage.CompressedManifestStaticFilesStorage`
# qui est le storage manifesté de production : il REFUSE de servir un fichier
# qui n'a pas été passé par `collectstatic` au préalable, et retourne une
# chaîne vide pour `{% static '...' %}` quand le fichier n'est pas dans le
# manifest. Conséquence en dev : tout `<script src="{% static '...' %}">`
# devient `<script src="">` → script jamais chargé → LeoWS undefined.
#
# En dev, on veut le comportement Django par défaut : servir directement
# depuis STATICFILES_DIRS sans manifest. C'est ce que fait `runserver`
# tant que STATICFILES_STORAGE est le default.
STORAGES["staticfiles"] = {
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
