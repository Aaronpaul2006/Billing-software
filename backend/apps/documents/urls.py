from django.urls import path

from . import views

urlpatterns = [
    path("documents", views.DocumentListView.as_view(), name="documents"),
    path(
        "documents:preview-totals",
        views.PreviewTotalsView.as_view(),
        name="document-preview-totals",
    ),
    path(
        "documents/<uuid:document_id>", views.DocumentDetailView.as_view(), name="document-detail"
    ),
]
