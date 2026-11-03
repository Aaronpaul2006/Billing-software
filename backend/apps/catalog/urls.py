from django.urls import path

from . import views

urlpatterns = [
    path("catalog-items:import", views.CatalogImportView.as_view(), name="catalog-import"),
    path(
        "catalog-items:import-sample",
        views.CatalogImportSampleView.as_view(),
        name="catalog-import-sample",
    ),
    path("catalog-items", views.CatalogItemListView.as_view(), name="catalog-items"),
    path(
        "catalog-items/<uuid:item_id>",
        views.CatalogItemDetailView.as_view(),
        name="catalog-item-detail",
    ),
    path(
        "catalog-items/<uuid:item_id>/variants",
        views.CatalogVariantListView.as_view(),
        name="catalog-item-variants",
    ),
    path(
        "catalog-variants/<uuid:variant_id>",
        views.CatalogVariantDetailView.as_view(),
        name="catalog-variant-detail",
    ),
]
