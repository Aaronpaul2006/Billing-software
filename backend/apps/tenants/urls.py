from django.urls import path

from . import views

urlpatterns = [
    path("tenant", views.TenantView.as_view(), name="tenant"),
    path("gst-registrations", views.GstRegistrationListView.as_view(), name="gst-registrations"),
    path(
        "gst-registrations/<uuid:registration_id>",
        views.GstRegistrationDetailView.as_view(),
        name="gst-registration-detail",
    ),
    path("document-series", views.DocumentSeriesListView.as_view(), name="document-series"),
    path(
        "document-series/<uuid:series_id>",
        views.DocumentSeriesDetailView.as_view(),
        name="document-series-detail",
    ),
]
