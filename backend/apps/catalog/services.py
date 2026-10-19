"""Catalog: reusable items and rates (docs/02-api-design.md §4)."""

import uuid
from typing import Any

from django.db import transaction

from apps.core.errors import Conflict
from apps.core.permissions import require
from apps.core.queries import get_or_404
from apps.core.tenancy import Principal
from apps.core.versioning import update_versioned
from apps.documents.models import DocumentLine

from .models import CatalogItem


def get_item(principal: Principal, item_id: uuid.UUID) -> CatalogItem:
    require(principal, "tenant.read")
    return get_or_404(CatalogItem, item_id)


def create_item(principal: Principal, data: dict[str, Any]) -> CatalogItem:
    require(principal, "masters.edit")
    item = CatalogItem(**data)
    item.save()
    return item


def update_item(
    principal: Principal, item_id: uuid.UUID, expected: int, changes: dict[str, Any]
) -> CatalogItem:
    require(principal, "masters.edit")
    with transaction.atomic():
        get_or_404(CatalogItem, item_id, for_update=True)
        update_versioned(CatalogItem.objects, item_id, expected, **changes)
    return get_or_404(CatalogItem, item_id)


def delete_item(principal: Principal, item_id: uuid.UUID) -> None:
    """Only never-used items; used ones are archived (is_active = false)."""
    require(principal, "masters.edit")
    with transaction.atomic():
        item = get_or_404(CatalogItem, item_id, for_update=True)
        if DocumentLine.objects.filter(catalog_item_id=item.pk).exists():
            raise Conflict(
                "Documents use this item; archive it instead (is_active: false).",
                code="catalog_item_used",
            )
        item.delete()
