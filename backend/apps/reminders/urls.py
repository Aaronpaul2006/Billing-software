from django.urls import path

from . import views

urlpatterns = [
    path(
        "documents/<uuid:document_id>/reminders",
        views.DocumentRemindersView.as_view(),
        name="document-reminders",
    ),
]
