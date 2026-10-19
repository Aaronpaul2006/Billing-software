from collections.abc import Callable

from django.http import HttpRequest, HttpResponse
from django.urls import Resolver404, resolve

from .services import session_is_live
from .tokens import InvalidToken, verify_access_token


def _ignores_access_token(request: HttpRequest) -> bool:
    """Public sign-in endpoints (signup, login, ...) ignore any bearer token, so
    a stale token never stops a user from signing in again. Resolved here
    because middleware runs before Django resolves the URL."""
    try:
        match = resolve(request.path_info)
    except Resolver404:
        return False
    view_class = getattr(match.func, "view_class", None)
    return bool(getattr(view_class, "ignores_access_token", False))


class JWTAuthenticationMiddleware:
    """Verifies `Authorization: Bearer <access token>` and sets request.principal.

    Runs before TenantContextMiddleware, which turns the principal into the
    request's tenant context. A bad token does not fail here: the reason is
    stored in request.auth_error and PrincipalAuthentication answers 401, so
    every error goes through the same problem+json handler.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request.principal = None  # type: ignore[attr-defined]
        request.auth_error = None  # type: ignore[attr-defined]
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if header and not _ignores_access_token(request):
            scheme, _, token = header.partition(" ")
            if scheme.lower() != "bearer" or not token.strip():
                request.auth_error = "invalid_token"  # type: ignore[attr-defined]
            else:
                try:
                    principal = verify_access_token(token.strip())
                except InvalidToken as exc:
                    request.auth_error = exc.code  # type: ignore[attr-defined]
                else:
                    if principal.session_id is None or not session_is_live(principal.session_id):
                        request.auth_error = "session_revoked"  # type: ignore[attr-defined]
                    else:
                        request.principal = principal  # type: ignore[attr-defined]
        return self.get_response(request)
