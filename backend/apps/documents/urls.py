from django.urls import path

from . import views

urlpatterns = [
    path("documents", views.DocumentListView.as_view(), name="documents"),
    path("documents:parse-lines", views.ParseLinesView.as_view(), name="document-parse-lines"),
    path("documents:lines-sample", views.LinesSampleView.as_view(), name="document-lines-sample"),
    path(
        "documents:preview-totals",
        views.PreviewTotalsView.as_view(),
        name="document-preview-totals",
    ),
    path(
        "documents/<uuid:document_id>", views.DocumentDetailView.as_view(), name="document-detail"
    ),
    path(
        "documents/<uuid:document_id>/issue",
        views.IssueView.as_view(),
        name="document-issue",
    ),
    path(
        "documents/<uuid:document_id>/cancel",
        views.CancelView.as_view(),
        name="document-cancel",
    ),
    path(
        "documents/<uuid:document_id>/accept",
        views.AcceptView.as_view(),
        name="document-accept",
    ),
    path(
        "documents/<uuid:document_id>/decline",
        views.DeclineView.as_view(),
        name="document-decline",
    ),
    path(
        "documents/<uuid:document_id>/convert",
        views.ConvertView.as_view(),
        name="document-convert",
    ),
    path(
        "documents/<uuid:document_id>/credit-notes",
        views.CreditNoteView.as_view(),
        name="document-credit-notes",
    ),
    path(
        "documents/<uuid:document_id>/debit-notes",
        views.DebitNoteView.as_view(),
        name="document-debit-notes",
    ),
    path("documents/<uuid:document_id>/pdf", views.DocumentPdfView.as_view(), name="document-pdf"),
]
