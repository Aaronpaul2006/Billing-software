from django.urls import path

from . import views

urlpatterns = [
    path("parties", views.PartyListView.as_view(), name="parties"),
    path("parties/<uuid:party_id>", views.PartyDetailView.as_view(), name="party-detail"),
]
