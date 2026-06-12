from django.urls import path
from .views import BrokerAccountListView, BrokerAccountCreateView, BrokerAccountUpdateView, BrokerAccountDeleteView, \
    BrokerAccountDetailView, BrokerAccountSetDefaultView, BrokerAccountTestConnectionView, broker_health_api

urlpatterns = [
    path("", BrokerAccountListView.as_view(), name="broker-list"),
    path("health/api/", broker_health_api, name="broker-health-api"),
    path("create/", BrokerAccountCreateView.as_view(), name="broker-create"),
    path("<int:pk>/edit/", BrokerAccountUpdateView.as_view(), name="broker-update"),
    path("<int:pk>/delete/", BrokerAccountDeleteView.as_view(), name="broker-delete"),
    path("<int:pk>/", BrokerAccountDetailView.as_view(), name="broker-detail"),

    path("<int:pk>/set-default/", BrokerAccountSetDefaultView.as_view(), name="broker-set-default"),
    path("<int:pk>/test-connection/", BrokerAccountTestConnectionView.as_view(), name="broker-test-connection"),
]