from django.urls import re_path

from .consumers import NotificationCenterConsumer

websocket_urlpatterns = [
    # Remplace l'ancien UserNotificationsConsumer (execution.routing) :
    # même groupe channel-layer, même événement notification.created,
    # plus les actions mark_read / mark_all_read / badge non-lu.
    re_path(r"ws/notifications/$", NotificationCenterConsumer.as_asgi()),
]
