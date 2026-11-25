from django.urls import path
from .views import (
    OrderListView,
    OrderDetailView,
    CancelOrderView,
)

app_name = "execution"

urlpatterns = [
    path("orders/", OrderListView.as_view(), name="order_list"),
    path("orders/<int:pk>/", OrderDetailView.as_view(), name="order_detail"),
    path("orders/<int:pk>/cancel/", CancelOrderView.as_view(), name="order_cancel"),
]