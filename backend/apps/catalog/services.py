"""Catalog: reusable items and rates (docs/02-api-design.md §4)."""

import uuid
from typing import Any

from django.db import IntegrityError, transaction

from apps.core.errors import Conflict
from apps.core.permissions import require
from apps.core.queries import get_or_404
from apps.core.tenancy import Principal
from apps.core.versioning import update_versioned
from apps.documents.models import DocumentLine

from .models import CatalogItem, CatalogItemVariant


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
        CatalogItemVariant.objects.filter(catalog_item_id=item.pk).delete()
        item.delete()


# --- variants (W.4) ------------------------------------------------------------------------


def _variant_taken() -> Conflict:
    return Conflict("This item already has that variant.", code="variant_exists")


def list_variants(principal: Principal, item_id: uuid.UUID) -> list[CatalogItemVariant]:
    require(principal, "tenant.read")
    get_or_404(CatalogItem, item_id)
    return list(
        CatalogItemVariant.objects.filter(catalog_item_id=item_id).order_by("attribute", "value")
    )


def get_variant(principal: Principal, variant_id: uuid.UUID) -> CatalogItemVariant:
    require(principal, "tenant.read")
    return get_or_404(CatalogItemVariant, variant_id)


def create_variant(
    principal: Principal, item_id: uuid.UUID, data: dict[str, Any]
) -> CatalogItemVariant:
    require(principal, "masters.edit")
    get_or_404(CatalogItem, item_id)
    try:
        with transaction.atomic():
            variant = CatalogItemVariant(catalog_item_id=item_id, **data)
            variant.save()
    except IntegrityError as exc:
        raise _variant_taken() from exc
    return variant


def update_variant(
    principal: Principal, variant_id: uuid.UUID, expected: int, changes: dict[str, Any]
) -> CatalogItemVariant:
    require(principal, "masters.edit")
    try:
        with transaction.atomic():
            get_or_404(CatalogItemVariant, variant_id, for_update=True)
            update_versioned(CatalogItemVariant.objects, variant_id, expected, **changes)
    except IntegrityError as exc:
        raise _variant_taken() from exc
    return get_or_404(CatalogItemVariant, variant_id)


def delete_variant(principal: Principal, variant_id: uuid.UUID) -> None:
    """Only never-used variants; used ones are archived (is_active = false)."""
    require(principal, "masters.edit")
    with transaction.atomic():
        variant = get_or_404(CatalogItemVariant, variant_id, for_update=True)
        if DocumentLine.objects.filter(catalog_variant_id=variant.pk).exists():
            raise Conflict(
                "Documents use this variant; archive it instead (is_active: false).",
                code="variant_used",
            )
        variant.delete()
