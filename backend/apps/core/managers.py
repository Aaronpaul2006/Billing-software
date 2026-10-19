"""Isolation layer 1 (docs/01-architecture.md §2.2): tenant-aware models.

`Model.objects` on a tenant-owned business table is always filtered to the
current tenant and raises if no tenant context is active, so a forgotten
context is a loud error rather than an empty page. Saving fills tenant_id
from the context and refuses a different one.

RLS and composite foreign keys (layers 2 and 3) remain the guarantee; this
layer catches mistakes earlier, with clearer errors.

Not used for users, tenants, memberships and auth_sessions: those are read
across tenants by design (login, tenant switcher, invitations).
"""

from typing import Any

from django.db import models

from .tenancy import TenantContextError, current_tenant_id


class CurrentTenantId(models.Expression):
    """The active tenant id, read when the query is compiled to SQL.

    Building or inspecting a queryset needs no context (django-filter and
    drf-spectacular do that at import / schema time); *running* one without
    a tenant context raises TenantContextError.
    """

    output_field = models.UUIDField()

    def as_sql(self, compiler: Any, connection: Any) -> tuple[str, list[Any]]:
        return "%s", [current_tenant_id()]


class TenantManager(models.Manager[Any]):
    def get_queryset(self) -> models.QuerySet[Any]:
        return super().get_queryset().filter(tenant_id=CurrentTenantId())


class TenantScoped(models.Model):
    """Mixin for models with a `tenant` foreign key to tenants.Tenant."""

    objects = TenantManager()

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        tenant_id = current_tenant_id()
        own: Any = getattr(self, "tenant_id", None)
        if own is None:
            self.tenant_id = tenant_id
        elif own != tenant_id:
            raise TenantContextError(
                f"{type(self).__name__} belongs to another tenant than the active context"
            )
        super().save(*args, **kwargs)
