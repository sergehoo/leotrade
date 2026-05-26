# /Users/ogahserge/Documents/leoTrade/execution/routing.py

from django.urls import re_path
from .consumers import UserOrdersConsumer, UserNotificationsConsumer

websocket_urlpatterns = [
    re_path(r"ws/orders/$", UserOrdersConsumer.as_asgi()),
    re_path(r"ws/notifications/$", UserNotificationsConsumer.as_asgi()),
]