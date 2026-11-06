from django.urls import path

from . import views

urlpatterns = [
    path("vendor-bills", views.VendorBillListView.as_view(), name="vendor-bills"),
    path(
        "vendor-bills/tds-suggestion",
        views.TdsSuggestionView.as_view(),
        name="vendor-bill-tds-suggestion",
    ),
    path(
        "vendor-bills/<uuid:bill_id>",
        views.VendorBillDetailView.as_view(),
        name="vendor-bill-detail",
    ),
    path(
        "vendor-bills/<uuid:bill_id>/void",
        views.VendorBillVoidView.as_view(),
        name="vendor-bill-void",
    ),
    path("vendor-payments", views.VendorPaymentListView.as_view(), name="vendor-payments"),
    path(
        "vendor-payments/<uuid:payment_id>",
        views.VendorPaymentDetailView.as_view(),
        name="vendor-payment-detail",
    ),
    path(
        "vendor-payments/<uuid:payment_id>/void",
        views.VendorPaymentVoidView.as_view(),
        name="vendor-payment-void",
    ),
    path("reports/payables", views.PayablesReportView.as_view(), name="report-payables"),
    path("work-orders", views.WorkOrderListView.as_view(), name="work-orders"),
    path("work-orders/<uuid:wo_id>", views.WorkOrderDetailView.as_view(), name="work-order-detail"),
    path(
        "work-orders/<uuid:wo_id>/close",
        views.WorkOrderCloseView.as_view(),
        name="work-order-close",
    ),
    path(
        "work-orders/<uuid:wo_id>/reopen",
        views.WorkOrderReopenView.as_view(),
        name="work-order-reopen",
    ),
    path(
        "work-orders/<uuid:wo_id>/retention-releases",
        views.RetentionReleaseCreateView.as_view(),
        name="work-order-retention-releases",
    ),
    path(
        "vendor-retention-releases",
        views.RetentionReleaseListView.as_view(),
        name="vendor-retention-releases",
    ),
    path(
        "vendor-retention-releases/<uuid:release_id>/cancel",
        views.RetentionReleaseCancelView.as_view(),
        name="vendor-retention-release-cancel",
    ),
    path(
        "work-orders/<uuid:wo_id>/ra-bills",
        views.RaBillCreateView.as_view(),
        name="work-order-ra-bills",
    ),
]
