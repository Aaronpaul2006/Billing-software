"""Errors as RFC 9457 `application/problem+json`.

Every error body has the same shape (see docs/02-api-design.md §1):
type, title, status, code, detail, optional `errors` (per field) and
`request_id`. Raw database or Python messages are never returned.
"""

from http import HTTPStatus
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404, HttpRequest
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.settings import api_settings

PROBLEM_CONTENT_TYPE = "application/problem+json"


def problem_body(
    request: HttpRequest | None,
    *,
    status: int,
    code: str,
    title: str | None = None,
    detail: str | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": f"/errors/{code}",
        "title": title or HTTPStatus(status).phrase,
        "status": status,
        "code": code,
    }
    if detail:
        body["detail"] = detail
    if errors is not None:
        body["errors"] = errors
    body["request_id"] = getattr(request, "request_id", None)
    return body


def flatten_validation_errors(detail: Any, path: str = "") -> list[dict[str, Any]]:
    """Turn DRF's nested error structure into a flat list with field paths.

    {"lines": [{}, {"rate": [ErrorDetail(...)]}]} → field "lines[1].rate".
    """
    out: list[dict[str, Any]] = []
    if isinstance(detail, dict):
        for key, value in detail.items():
            if key == api_settings.NON_FIELD_ERRORS_KEY:
                out += flatten_validation_errors(value, path)
            elif isinstance(key, int):
                # DRF 3.18+ reports `many=True` errors as {index: errors}.
                out += flatten_validation_errors(value, f"{path}[{key}]")
            else:
                out += flatten_validation_errors(value, f"{path}.{key}" if path else str(key))
    elif isinstance(detail, list):
        for i, item in enumerate(detail):
            if isinstance(item, dict | list):
                out += flatten_validation_errors(item, f"{path}[{i}]")
            else:
                out += flatten_validation_errors(item, path)
    else:
        out.append(
            {
                "field": path or None,
                "code": getattr(detail, "code", "invalid"),
                "message": str(detail),
            }
        )
    return out


def problem_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """DRF EXCEPTION_HANDLER. Unhandled exceptions return None → handler500."""
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied()
    if not isinstance(exc, exceptions.APIException):
        return None

    request = context.get("request")
    headers: dict[str, str] = {}

    if isinstance(exc, exceptions.ValidationError):
        errors = flatten_validation_errors(exc.detail)
        n = len(errors)
        body = problem_body(
            request,
            status=422,
            code="validation_error",
            title="Validation failed",
            detail=f"{n} field{'s are' if n != 1 else ' is'} invalid.",
            errors=errors,
        )
    else:
        status = exc.status_code
        codes = exc.get_codes()
        code = codes if isinstance(codes, str) else exc.default_code
        body = problem_body(request, status=status, code=code, detail=str(exc.detail))
        wait = getattr(exc, "wait", None)  # Throttled only; missing from the type stubs
        if wait is not None:
            headers["Retry-After"] = str(int(wait))
        auth_header = getattr(exc, "auth_header", None)
        if auth_header:
            headers["WWW-Authenticate"] = auth_header

    return Response(body, status=body["status"], headers=headers, content_type=PROBLEM_CONTENT_TYPE)
