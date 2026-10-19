from django.urls import path

from . import views

urlpatterns = [
    path("projects", views.ProjectListView.as_view(), name="projects"),
    path("projects/<uuid:project_id>", views.ProjectDetailView.as_view(), name="project-detail"),
    path(
        "projects/<uuid:project_id>/boq-items",
        views.BoqItemListView.as_view(),
        name="project-boq-items",
    ),
    path("boq-items/<uuid:item_id>", views.BoqItemDetailView.as_view(), name="boq-item-detail"),
]
