from django.urls import path

from portfolio.views import PortfolioListView, PortfolioDetailView, PortfolioCreateView, PortfolioUpdateView, \
    PortfolioDeleteView, PortfolioSetDefaultView, PortfolioSnapshotCreateView, PositionCreateView, PositionUpdateView, \
    PositionDeleteView, PortfolioImportLiveView

urlpatterns = [
    path("", PortfolioListView.as_view(), name="portfolio-list"),
    path("create/", PortfolioCreateView.as_view(), name="portfolio-create"),
    path("<int:pk>/", PortfolioDetailView.as_view(), name="portfolio-detail"),
    path("<int:pk>/edit/", PortfolioUpdateView.as_view(), name="portfolio-update"),
    path("<int:pk>/delete/", PortfolioDeleteView.as_view(), name="portfolio-delete"),
    path("<int:pk>/set-default/", PortfolioSetDefaultView.as_view(), name="portfolio-set-default"),
    path("<int:pk>/snapshot/", PortfolioSnapshotCreateView.as_view(), name="portfolio-snapshot-create"),

    path("<int:portfolio_pk>/positions/create/", PositionCreateView.as_view(), name="position-create"),
    path("positions/<int:pk>/edit/", PositionUpdateView.as_view(), name="position-update"),
    path("positions/<int:pk>/delete/", PositionDeleteView.as_view(), name="position-delete"),
    path("<int:pk>/import-live/", PortfolioImportLiveView.as_view(), name="portfolio-import-live"),

]