from django.urls import path

from . import views

urlpatterns = [
    path("payments", views.PaymentListView.as_view(), name="payments"),
    path("payments/<uuid:payment_id>", views.PaymentDetailView.as_view(), name="payment-detail"),
    path(
        "payments/<uuid:payment_id>/allocations",
        views.PaymentAllocationsView.as_view(),
        name="payment-allocations",
    ),
    path("payments/<uuid:payment_id>/void", views.PaymentVoidView.as_view(), name="payment-void"),
    path(
        "allocations/<uuid:allocation_id>",
        views.AllocationDetailView.as_view(),
        name="allocation-detail",
    ),
]
