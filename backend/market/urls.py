from django.urls import path
from .views import (
    AssetListView,
    AssetDetailView,
    AssetQuickTradeView,
    CandleListView,
    CandleDetailView,
    CandleLiveFeedView,
    market_assets_api,
)

urlpatterns = [
    path("assets/", AssetListView.as_view(), name="asset-list"),
    path("assets/api/", market_assets_api, name="market-assets-api"),
    path("assets/<int:pk>/", AssetDetailView.as_view(), name="asset-detail"),
    path("assets/<int:pk>/trade/", AssetQuickTradeView.as_view(), name="asset-quick-trade"),
    path("candles/", CandleListView.as_view(), name="candle-list"),
    path("assets/<int:pk>/chart/", CandleDetailView.as_view(), name="asset-chart"),
    path("assets/<int:pk>/candles/live/", CandleLiveFeedView.as_view(), name="candle-live-feed"),
]