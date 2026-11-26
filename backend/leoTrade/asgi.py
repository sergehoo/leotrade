import os

default_settings = (
    "leoTrade.settings.prod"
    if os.environ.get("DJANGO_ENV") == "prod"
    else "leoTrade.settings.dev"
)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", default_settings)

from django.core.asgi import get_asgi_application
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator

from core.ws_auth import JWTAuthMiddlewareStack

import execution.routing
import notifications.routing
import portfolio.routing
import trading.routing
import market.routing
import ai_assistant.routing

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        # JWT d'abord (React, Flutter), session en repli (écrans Django).
        JWTAuthMiddlewareStack(
            URLRouter(
                ai_assistant.routing.websocket_urlpatterns   # panel IA — prioritaire
                + notifications.routing.websocket_urlpatterns  # centre de notifications
                + execution.routing.websocket_urlpatterns
                + portfolio.routing.websocket_urlpatterns
                + trading.routing.websocket_urlpatterns
                + market.routing.websocket_urlpatterns
            )
        )
    ),
})
