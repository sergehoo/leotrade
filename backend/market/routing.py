# market/routing.py
from django.urls import re_path

from market.servicess.consumers import CandleConsumer

# from .consumers import CandleConsumer

websocket_urlpatterns = [
    re_path(
        r"ws/market/candles/(?P<asset_id>\d+)/(?P<timeframe>[A-Za-z0-9]+)/$",
        CandleConsumer.as_asgi(),
    ),
]