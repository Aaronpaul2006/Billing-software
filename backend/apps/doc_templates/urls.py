from django.urls import path

from . import views

urlpatterns = [
    path("document-templates", views.TemplateListView.as_view(), name="document-templates"),
    path(
        "document-templates/<uuid:template_id>",
        views.TemplateDetailView.as_view(),
        name="document-template-detail",
    ),
    path(
        "document-templates/<uuid:template_id>/use",
        views.TemplateUseView.as_view(),
        name="document-template-use",
    ),
    path(
        "documents/<uuid:document_id>/save-as-template",
        views.SaveAsTemplateView.as_view(),
        name="document-save-as-template",
    ),
]
