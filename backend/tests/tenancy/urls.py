"""Test-only views and middleware for exercising TenantContextMiddleware."""

import uuid
from collections.abc import Callable

from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import path

from apps.catalog.models import CatalogItem
from apps.core.tenancy import Principal, current_tenant_id

PRINCIPAL_HEADER = "HTTP_X_TEST_PRINCIPAL"


class FakeAuthenticationMiddleware:
    """Stands in for access-token verification (step 5) in these tests only:
    builds request.principal from a test header "<tenant_id>:<user_id>"."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        raw = request.META.get(PRINCIPAL_HEADER)
        if raw:
            tenant_id, user_id = raw.split(":")
            request.principal = Principal(  # type: ignore[attr-defined]
                user_id=uuid.UUID(user_id), tenant_id=uuid.UUID(tenant_id), role="OWNER"
            )
        return self.get_response(request)


def whoami(request: HttpRequest) -> JsonResponse:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT app_current_tenant(), app_current_user_id(),"
            " current_setting('app.request_id', true), pg_backend_pid(),"
            " (SELECT count(*) FROM parties)"
        )
        tenant, user, request_id, pid, parties = cursor.fetchone()
    return JsonResponse(
        {
            "tenant_id": str(tenant) if tenant else None,
            "user_id": str(user) if user else None,
            "request_id": request_id or None,
            "backend_pid": pid,
            "parties_visible": parties,
        }
    )


def write_then_fail(request: HttpRequest) -> JsonResponse:
    CatalogItem.objects.create(tenant_id=current_tenant_id(), name=request.GET["name"])
    raise RuntimeError("boom after writing")


urlpatterns = [
    path("whoami", whoami),
    path("write-then-fail", write_then_fail),
]
