"""
WSGI config for leoTrade project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

default_settings = (
    "leoTrade.settings.prod"
    if os.environ.get("DJANGO_ENV") == "prod"
    else "leoTrade.settings.dev"
)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", default_settings)

application = get_wsgi_application()
