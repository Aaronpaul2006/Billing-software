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
    path(
        "documents/<uuid:document_id>/allocations",
        views.DocumentAllocationsView.as_view(),
        name="document-allocations",
    ),
    path(
        "retention-releases",
        views.RetentionReleaseListView.as_view(),
        name="retention-releases",
    ),
    path(
        "retention-releases/<uuid:release_id>",
        views.RetentionReleaseDetailView.as_view(),
        name="retention-release-detail",
    ),
    path(
        "retention-releases/<uuid:release_id>/cancel",
        views.RetentionReleaseCancelView.as_view(),
        name="retention-release-cancel",
    ),
    path(
        "projects/<uuid:project_id>/retention",
        views.ProjectRetentionView.as_view(),
        name="project-retention",
    ),
]
