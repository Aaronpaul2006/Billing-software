"""Small query helpers for services."""

from typing import Any, TypeVar

from django.db.models import Model

from .errors import Invalid, NotFound

M = TypeVar("M", bound=Model)


def get_or_404[M: Model](model: type[M], pk: Any, *, for_update: bool = False) -> M:
    """The object in the current tenant, or 404 (also for other tenants' ids)."""
    manager: Any = model._default_manager
    queryset = manager.select_for_update() if for_update else manager.all()
    obj = queryset.filter(pk=pk).first()
    if obj is None:
        raise NotFound
    return obj  # type: ignore[no-any-return]


def get_or_invalid[M: Model](model: type[M], pk: Any, field: str, *, label: str) -> M:
    """For ids sent in a request body: unknown (or another tenant's) → 422."""
    obj = model._default_manager.filter(pk=pk).first()
    if obj is None:
        raise Invalid(field, f"No such {label}.", code="not_found")
    return obj
