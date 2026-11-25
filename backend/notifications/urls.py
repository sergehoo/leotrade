from django.urls import path

from .views import notification_center, notification_preferences

app_name = "notifications"

urlpatterns = [
    path("", notification_center, name="center"),
    path("preferences/", notification_preferences, name="preferences"),
]
