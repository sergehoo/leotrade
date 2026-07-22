from django.urls import path, include

from dashboard.views import HedgeFundDashboardView, trading_mode_toggle, kyc_dashboard, kyc_submit, admin_kyc_list, \
    admin_kyc_detail, admin_kyc_document, admin_kyc_approve, admin_kyc_reject, HedgeFundDashboardLiveDataView
from leo_backtesting.views import BacktestListView, BacktestDetailView, LaunchBacktestView

urlpatterns = [
    path("", HedgeFundDashboardView.as_view(), name="dashboard"),
    path("", include("dashboard.urls_premium")),

    path("fund-dashboard/live/", HedgeFundDashboardLiveDataView.as_view(), name="fund-dashboard-live"),
    path("trading/mode-toggle/", trading_mode_toggle, name="trading-mode-toggle"),

    path("kyc_dashboard/", kyc_dashboard, name="kyc-dashboard"),
    path("submit/", kyc_submit, name="kyc-submit"),

    path("admin/list/", admin_kyc_list, name="admin-kyc-list"),
    path("admin/<int:pk>/", admin_kyc_detail, name="admin-kyc-detail"),
    path("admin/<int:pk>/documents/<str:field_name>/", admin_kyc_document, name="admin-kyc-document"),
    path("admin/<int:pk>/approve/", admin_kyc_approve, name="admin-kyc-approve"),
    path("admin/<int:pk>/reject/", admin_kyc_reject, name="admin-kyc-reject"),
]
