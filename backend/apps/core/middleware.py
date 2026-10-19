import uuid
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

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
