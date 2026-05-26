from django.urls import re_path
from .consumers import DashboardConsumer
from .consumers_ai import AIRadarConsumer

websocket_urlpatterns = [
    re_path(r"ws/dashboard/live/$", DashboardConsumer.as_asgi()),
    re_path(r"ws/ai/radar/$", AIRadarConsumer.as_asgi()),
]