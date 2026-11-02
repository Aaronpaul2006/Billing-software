from django.urls import path

from . import views

urlpatterns = [
    path("portal/me", views.MeView.as_view(), name="portal-me"),
    path("portal/documents", views.DocumentListView.as_view(), name="portal-documents"),
    path(
        "portal/documents/<uuid:document_id>",
        views.DocumentDetailView.as_view(),
        name="portal-document-detail",
    ),
    path(
        "portal/documents/<uuid:document_id>/pdf",
        views.DocumentPdfView.as_view(),
        name="portal-document-pdf",
    ),
    path(
        "portal/documents/<uuid:document_id>/accept",
        views.QuotationResponseView.as_view(),
        name="portal-document-accept",
    ),
    path(
        "portal/documents/<uuid:document_id>/decline",
        views.QuotationDeclineView.as_view(),
        name="portal-document-decline",
    ),
    path("portal/payments", views.PaymentListView.as_view(), name="portal-payments"),
    path("portal/statement", views.StatementView.as_view(), name="portal-statement"),
    path("portal/projects", views.ProjectListView.as_view(), name="portal-projects"),
    path(
        "portal/projects/<uuid:project_id>/boq-progress",
        views.BoqProgressView.as_view(),
        name="portal-boq-progress",
    ),
]
