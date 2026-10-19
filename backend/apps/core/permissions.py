"""Permission checks, named by action (docs/01-architecture.md §3).

The role/action matrix arrives in Phase 0 step 6; this module starts with
the MFA rule that applies to every endpoint.
"""

from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from .tenancy import Principal

MFA_REQUIRED_ROLES = frozenset({"OWNER", "ADMIN"})


class MfaSatisfied(BasePermission):
    """OWNER and ADMIN must have passed TOTP (amr contains "otp").

    A default permission, so it applies everywhere; only the endpoints needed
    to enrol (MFA setup, /me, sessions, logout) opt out.
    """

    message = "Turn on two-factor authentication to continue."
    code = "mfa_enrollment_required"

    def has_permission(self, request: Request, view: Any) -> bool:
        principal = request.auth
        if not isinstance(principal, Principal):
            return True  # unauthenticated: IsAuthenticated decides
        return principal.role not in MFA_REQUIRED_ROLES or "otp" in principal.amr
