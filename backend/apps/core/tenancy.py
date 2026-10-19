"""Tenant context: which tenant (and user) the database work belongs to.

The database enforces isolation with Row-Level Security keyed on
`app.tenant_id`; this module is the only place that sets it. Values are set
with set_config(..., is_local => true), i.e. for the current transaction
only, so they vanish at COMMIT/ROLLBACK and can never leak to the next
request that reuses a pooled connection (docs/01-architecture.md §2.4).

    with tenant_context(tenant_id, user_id):     # Celery task, command, test
        Party.objects.filter(...)                 # RLS-filtered to tenant_id
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from django.db import DEFAULT_DB_ALIAS, connections, transaction


@dataclass(frozen=True)
class Principal:
    """The authenticated caller, from a verified access token (Phase 0 step 5).

    Never built from client-controlled input: the tenant is the token's
    `tid` claim, not a URL or header.
    """

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str
    session_id: uuid.UUID | None = None


@dataclass(frozen=True)
class TenantContext:
    tenant_id: uuid.UUID
    user_id: uuid.UUID | None = None
    request_id: str | None = None


class TenantContextError(RuntimeError):
    pass


_current: ContextVar[TenantContext | None] = ContextVar("tenant_context", default=None)


def current_context() -> TenantContext | None:
    return _current.get()


def current_tenant_id() -> uuid.UUID:
    ctx = _current.get()
    if ctx is None:
        raise TenantContextError("no tenant context is active")
    return ctx.tenant_id


def _set_db_context(ctx: TenantContext | None, using: str) -> None:
    def text(value: object) -> str:
        return "" if value is None else str(value)  # '' → NULL in app_current_*()

    with connections[using].cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.tenant_id', %s, true),"
            "       set_config('app.user_id', %s, true),"
            "       set_config('app.request_id', %s, true)",
            [
                text(ctx and ctx.tenant_id),
                text(ctx and ctx.user_id),
                text(ctx and ctx.request_id),
            ],
        )


@contextmanager
def tenant_context(
    tenant_id: uuid.UUID | str,
    user_id: uuid.UUID | str | None = None,
    *,
    request_id: str | None = None,
    using: str = DEFAULT_DB_ALIAS,
) -> Iterator[TenantContext]:
    """Run the block in one transaction scoped to `tenant_id`.

    Re-entering for the same tenant and user is a no-op; switching to a
    different one while a context is active raises, so code can never mix
    two tenants' data in one transaction by accident.
    """
    ctx = TenantContext(
        tenant_id=uuid.UUID(str(tenant_id)),
        user_id=uuid.UUID(str(user_id)) if user_id is not None else None,
        request_id=request_id,
    )
    active = _current.get()
    if active is not None:
        if (active.tenant_id, active.user_id) != (ctx.tenant_id, ctx.user_id):
            raise TenantContextError(
                "a different tenant context is already active; finish it first"
            )
        yield active
        return

    nested = connections[using].in_atomic_block
    with transaction.atomic(using=using):
        _set_db_context(ctx, using)
        token = _current.set(ctx)
        try:
            yield ctx
        finally:
            _current.reset(token)
        if nested:
            # The enclosing transaction continues after this block: clear the
            # settings so later statements in it run without a tenant. (On an
            # exception the savepoint rollback reverts them anyway.)
            _set_db_context(None, using)
