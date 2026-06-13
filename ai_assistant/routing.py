from django.urls import re_path
from .consumers import AssistantConsumer

websocket_urlpatterns = [
    re_path(r"^ws/assistant/chat/$", AssistantConsumer.as_asgi()),
    # Connexion directe à une conversation précise (centre des conversations,
    # app mobile Flutter) — même consumer, conversation épinglée.
    re_path(r"^ws/assistant/conversation/(?P<conversation_id>\d+)/$", AssistantConsumer.as_asgi()),
]
