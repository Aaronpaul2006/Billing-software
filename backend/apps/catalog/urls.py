from django.urls import path

from . import views

urlpatterns = [
    path("catalog-items", views.CatalogItemListView.as_view(), name="catalog-items"),
    path(
        "catalog-items/<uuid:item_id>",
        views.CatalogItemDetailView.as_view(),
        name="catalog-item-detail",
    ),
]
