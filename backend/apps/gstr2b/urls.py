from django.urls import path

from . import views

urlpatterns = [
    path("gstr2b-returns", views.Gstr2bReturnListView.as_view(), name="gstr2b-returns"),
    path(
        "gstr2b-returns/<uuid:return_id>/reconciliation",
        views.ReconciliationView.as_view(),
        name="gstr2b-reconciliation",
    ),
]
