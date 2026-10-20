from django.urls import path

from . import views

urlpatterns = [
    path("tds-certificates", views.TdsCertificateListView.as_view(), name="tds-certificates"),
    path(
        "tds-certificates/<uuid:certificate_id>",
        views.TdsCertificateDetailView.as_view(),
        name="tds-certificate-detail",
    ),
]
