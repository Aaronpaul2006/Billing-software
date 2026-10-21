from django.urls import path

from . import views

urlpatterns = [
    path("exports", views.ExportListView.as_view(), name="exports"),
    path("exports/<uuid:export_id>", views.ExportDetailView.as_view(), name="export-detail"),
]
