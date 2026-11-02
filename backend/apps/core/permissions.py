"""Permission checks, named by action (docs/01-architecture.md §3).

Roles are per membership (per tenant). The matrix below is the single source
of truth for what each role may do; views use HasAction("..."), services use
require(principal, "..."). tests/core/test_permissions.py checks it cell by
cell against the architecture document.
"""

from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from .errors import Forbidden
from .tenancy import Principal

OWNER, ADMIN, ACCOUNTANT, SITE_ENGINEER, VIEWER = (
    "OWNER",
    "ADMIN",
    "ACCOUNTANT",
    "SITE_ENGINEER",
    "VIEWER",
)
ALL_ROLES = (OWNER, ADMIN, ACCOUNTANT, SITE_ENGINEER, VIEWER)
MFA_REQUIRED_ROLES = frozenset({OWNER, ADMIN})
# Client-portal users (W.5). In no ACTIONS set below, so every staff endpoint
# refuses them; the portal endpoints check for this role instead.
CLIENT = "CLIENT"

# action → roles allowed (docs/01-architecture.md §3, row by row)
ACTIONS: dict[str, frozenset[str]] = {
    # every member can read the tenant's master data and documents
    "tenant.read": frozenset(ALL_ROLES),
    # business settings, GST registrations, number series
    "tenant.settings": frozenset({OWNER, ADMIN}),
    # invite / change members (ADMIN cannot touch OWNER: see members service)
    "members.manage": frozenset({OWNER, ADMIN}),
    # create / edit parties, projects, catalog
    "masters.edit": frozenset({OWNER, ADMIN, ACCOUNTANT}),
    # edit BOQ and measurements
    "boq.edit": frozenset({OWNER, ADMIN, ACCOUNTANT, SITE_ENGINEER}),
    # create / edit draft documents
    "documents.draft": frozenset({OWNER, ADMIN, ACCOUNTANT, SITE_ENGINEER}),
    # issue / cancel documents, credit & debit notes
    "documents.issue": frozenset({OWNER, ADMIN, ACCOUNTANT}),
    # record / void payments
    "payments.record": frozenset({OWNER, ADMIN, ACCOUNTANT}),
    # record expenses
    "expenses.record": frozenset({OWNER, ADMIN, ACCOUNTANT, SITE_ENGINEER}),
    # upload files (bills, receipts, site photos)
    "files.upload": frozenset({OWNER, ADMIN, ACCOUNTANT, SITE_ENGINEER}),
    # dashboards & reports
    "reports.view": frozenset({OWNER, ADMIN, ACCOUNTANT, VIEWER}),
    # audit log
    "audit.view": frozenset({OWNER, ADMIN}),
    # transfer ownership / close tenant
    "tenant.ownership": frozenset({OWNER}),
}


def can(role: str, action: str) -> bool:
    try:
        return role in ACTIONS[action]
    except KeyError:
        raise ValueError(f"unknown action {action!r}") from None  # typo = bug, not "deny"


def require(principal: Principal, action: str) -> None:
    """For services: raise 403 unless the principal's role allows `action`."""
    if not can(principal.role, action):
        raise Forbidden


def HasAction(action: str) -> type[BasePermission]:  # noqa: N802 - reads like a class in views
    """DRF permission: `permission_classes = [IsAuthenticated, MfaSatisfied, HasAction(...)]`."""
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}")

    class _HasAction(BasePermission):
        message = "Your role does not allow this."
        code = "permission_denied"

        def has_permission(self, request: Request, view: Any) -> bool:
            principal = request.auth
            return isinstance(principal, Principal) and can(principal.role, action)

    _HasAction.__name__ = f"HasAction[{action}]"
    return _HasAction


class MfaSatisfied(BasePermission):
    """OWNER and ADMIN must have passed TOTP (amr contains "otp"); a CLIENT
    must have passed TOTP or a code emailed at sign-in ("email").

    A default permission, so it applies everywhere; only the endpoints needed
    to enrol (MFA setup, /me, sessions, logout) opt out.
    """

    message = "Turn on two-factor authentication to continue."
    code = "mfa_enrollment_required"

    def has_permission(self, request: Request, view: Any) -> bool:
        principal = request.auth
        if not isinstance(principal, Principal):
            return True  # unauthenticated: IsAuthenticated decides
        if principal.role == CLIENT:
            return bool({"otp", "email"} & principal.amr)
        return principal.role not in MFA_REQUIRED_ROLES or "otp" in principal.amr


class IsClient(BasePermission):
    """Client-portal endpoints: role CLIENT, which names its party."""

    message = "This is for client-portal users."
    code = "permission_denied"

    def has_permission(self, request: Request, view: Any) -> bool:
        principal = request.auth
        return (
            isinstance(principal, Principal)
            and principal.role == CLIENT
            and principal.party_id is not None
        )
