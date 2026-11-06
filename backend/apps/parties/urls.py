from django.urls import path

from . import views

urlpatterns = [
    path("parties", views.PartyListView.as_view(), name="parties"),
    path("parties:import", views.PartyImportView.as_view(), name="party-import"),
    path(
        "parties:import-sample", views.PartyImportSampleView.as_view(), name="party-import-sample"
    ),
    path("parties/<uuid:party_id>", views.PartyDetailView.as_view(), name="party-detail"),
    path("tally-imports", views.TallyImportView.as_view(), name="tally-import"),
]
