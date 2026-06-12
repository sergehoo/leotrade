"""API REST — montée sous /api/notifications/ (cf. leoTrade/urls.py)."""
from rest_framework.routers import DefaultRouter

from .api import NotificationViewSet

router = DefaultRouter()
router.register("", NotificationViewSet, basename="notification")

urlpatterns = router.urls
