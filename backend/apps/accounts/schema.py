"""OpenAPI description of the bearer-token scheme (loaded in AccountsConfig.ready)."""

from typing import Any

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class PrincipalAuthenticationScheme(OpenApiAuthenticationExtension):  # type: ignore[no-untyped-call]
    target_class = "apps.accounts.authentication.PrincipalAuthentication"
    name = "bearerAuth"

    def get_security_definition(self, auto_schema: Any) -> dict[str, str]:
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Access token from /auth/login, /auth/mfa/verify or /auth/token/refresh "
            "(10 minutes). The tenant is the token's `tid` claim.",
        }
