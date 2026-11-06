from django.urls import path

from . import views

urlpatterns = [
    path(
        "projects/<uuid:project_id>/diary",
        views.ProjectDiaryView.as_view(),
        name="project-diary",
    ),
    path("diary-entries/<uuid:entry_id>", views.DiaryEntryView.as_view(), name="diary-entry"),
    path(
        "diary-entries/<uuid:entry_id>/photos",
        views.DiaryPhotosView.as_view(),
        name="diary-entry-photos",
    ),
    path("diary-photos/<uuid:photo_id>", views.DiaryPhotoView.as_view(), name="diary-photo"),
    path(
        "documents/<uuid:document_id>/photos",
        views.DocumentPhotosView.as_view(),
        name="document-photos",
    ),
]
