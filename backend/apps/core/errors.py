"""Errors raised by services (plain functions, no DRF) that map to API problems.

The problem+json handler turns a DomainError into its status and stable
`code` (docs/02-api-design.md §1), e.g. 409 document_not_draft.
"""

# WWW-Authenticate value on every 401 (RFC 6750).
BEARER_CHALLENGE = 'Bearer realm="api"'


class DomainError(Exception):
    status = 400
    code = "bad_request"
    detail = "The request could not be processed."

    def __init__(self, detail: str | None = None, *, code: str | None = None) -> None:
        super().__init__(detail or self.detail)
        if detail:
            self.detail = detail
        if code:
            self.code = code


class Unauthenticated(DomainError):
    status = 401
    code = "not_authenticated"
    detail = "Authentication failed."


class Forbidden(DomainError):
    status = 403
    code = "permission_denied"
    detail = "You do not have permission to perform this action."


class NotFound(DomainError):
    """Also used for another tenant's objects: never reveal that they exist."""

    status = 404
    code = "not_found"
    detail = "Not found."


class Conflict(DomainError):
    status = 409
    code = "conflict"
    detail = "The resource is not in a state that allows this."


class Invalid(DomainError):
    """A single-field validation failure raised by a service."""

    status = 422
    code = "invalid"
    detail = "Invalid value."

    def __init__(self, field: str, detail: str, *, code: str = "invalid") -> None:
        super().__init__(detail, code=code)
        self.field = field
