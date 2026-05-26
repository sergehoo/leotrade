import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "leoTrade.settings")

from django.core.asgi import get_asgi_application
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator

import execution.routing
import portfolio.routing
import trading.routing
import market.routing

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(
                execution.routing.websocket_urlpatterns
                + portfolio.routing.websocket_urlpatterns
                + trading.routing.websocket_urlpatterns
                + market.routing.websocket_urlpatterns
            )
        )
    ),
})