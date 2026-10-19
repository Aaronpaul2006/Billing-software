import uuid
from typing import Any

from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

from apps.core.errors import BEARER_CHALLENGE
from apps.core.tenancy import Principal

AUTH_ERROR_DETAIL = {
    "token_expired": "The access token has expired.",
    "session_revoked": "This session has ended. Sign in again.",
    "invalid_token": "The access token is invalid.",
}


class AuthenticatedUser:
    """request.user for API views: the principal, plus what DRF expects."""

    is_authenticated = True
    is_anonymous = False

    def __init__(self, principal: Principal) -> None:
        self.principal = principal
        self.id: uuid.UUID = principal.user_id
        self.pk = principal.user_id

    def __str__(self) -> str:
        return str(self.id)


class PrincipalAuthentication(BaseAuthentication):
    """Reads what JWTAuthenticationMiddleware verified; never parses tokens itself."""

    def authenticate(self, request: Request) -> tuple[AuthenticatedUser, Principal] | None:
        django_request: Any = request._request
        error = getattr(django_request, "auth_error", None)
        if error:
            raise exceptions.AuthenticationFailed(
                AUTH_ERROR_DETAIL.get(error, AUTH_ERROR_DETAIL["invalid_token"]), code=error
            )
        principal: Principal | None = getattr(django_request, "principal", None)
        if principal is None:
            return None
        return AuthenticatedUser(principal), principal

    def authenticate_header(self, request: Request) -> str:
        return BEARER_CHALLENGE  # makes DRF answer 401 (not 403) when unauthenticated
