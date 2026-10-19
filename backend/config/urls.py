from django.conf import settings
from django.urls import URLPattern, URLResolver, include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.core import views as core_views

urlpatterns: list[URLPattern | URLResolver] = [
    path("healthz", core_views.healthz, name="healthz"),
    path("readyz", core_views.readyz, name="readyz"),
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/v1/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.tenants.urls")),
    path("api/v1/", include("apps.parties.urls")),
    path("api/v1/", include("apps.projects.urls")),
    path("api/v1/", include("apps.catalog.urls")),
]

if settings.DEBUG:
    urlpatterns.append(
        path("api/v1/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs")
    )

handler404 = "apps.core.views.not_found"
handler500 = "apps.core.views.server_error"
