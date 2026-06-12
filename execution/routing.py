# /Users/ogahserge/Documents/leoTrade/execution/routing.py

from django.urls import re_path
from .consumers import UserOrdersConsumer

websocket_urlpatterns = [
    re_path(r"ws/orders/$", UserOrdersConsumer.as_asgi()),
    # /ws/notifications/ est désormais servi par notifications.routing
    # (NotificationCenterConsumer : même groupe + badge non-lu + mark-read).
]