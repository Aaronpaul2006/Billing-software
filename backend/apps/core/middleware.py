import uuid
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from .tenancy import Principal, tenant_context

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIdMiddleware:
    """Gives every request a server-generated id (UUIDv7).

    It is returned in the `X-Request-ID` header and in error bodies, and is
    later written to the audit trail via `app.request_id`. A client-supplied
    id is ignored so it cannot be used to forge audit entries.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request.request_id = str(uuid.uuid7())  # type: ignore[attr-defined]
        response = self.get_response(request)
        response[REQUEST_ID_HEADER] = request.request_id  # type: ignore[attr-defined]
        return response


class TenantContextMiddleware:
    """Scopes an authenticated request's database work to its tenant.

    Django's ATOMIC_REQUESTS wraps only the view, so middleware cannot reach
    into that transaction. This middleware therefore opens the request
    transaction itself and sets the tenant context in it (transaction-local);
    the view's ATOMIC_REQUESTS block becomes a savepoint inside it, so a
    failing view still rolls back its own writes.

    The tenant comes only from `request.principal`, which is set solely by
    access-token verification, never from a client-controlled URL or header.
    Requests without a principal get no context: RLS then returns no rows.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        principal: Principal | None = getattr(request, "principal", None)
        if principal is None:
            return self.get_response(request)
        with tenant_context(
            principal.tenant_id,
            principal.user_id,
            request_id=getattr(request, "request_id", None),
        ):
            return self.get_response(request)
