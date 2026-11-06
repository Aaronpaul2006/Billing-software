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
]
