from django.urls import path

from . import views

urlpatterns = [
    path("tenant", views.TenantView.as_view(), name="tenant"),
    path("sample-business", views.SampleBusinessView.as_view(), name="sample-business"),
    path(
        "sample-business/remove",
        views.SampleBusinessRemoveView.as_view(),
        name="sample-business-remove",
    ),
    path("tenant/setup", views.SetupStatusView.as_view(), name="tenant-setup"),
    path("tenant/print-settings", views.PrintSettingsView.as_view(), name="tenant-print-settings"),
    path("tenant/tally-settings", views.TallySettingsView.as_view(), name="tenant-tally-settings"),
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
