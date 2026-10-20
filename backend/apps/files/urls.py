from django.urls import path

from . import views

urlpatterns = [
    path("attachments", views.AttachmentListView.as_view(), name="attachments"),
    path(
        "attachments/<uuid:attachment_id>",
        views.AttachmentDetailView.as_view(),
        name="attachment-detail",
    ),
    path(
        "attachments/<uuid:attachment_id>/complete",
        views.AttachmentCompleteView.as_view(),
        name="attachment-complete",
    ),
]
