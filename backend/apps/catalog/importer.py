"""Importing catalog items from a spreadsheet (B.2), all or nothing.

One row per item: name (required), description, unit, HSN/SAC, rate, GST %.
A name already in the catalog (any case, archived items too) or twice in the
file is refused, so an import never makes look-alike duplicates; change an
existing item on the Catalog page. Variants are added there too.
"""

from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.db.models.functions import Lower

from apps.core import sheets
from apps.core.imports import RowErrors, row_error, validate_rows
from apps.core.permissions import require
from apps.core.tenancy import Principal

from .models import CatalogItem

LAYOUT = sheets.Layout(
    columns={
        "name": ("name", "item", "item_name", "material", "particulars"),
        "description": ("description", "details"),
        "unit": ("unit", "uom", "units"),
        "sac_hsn": ("sac_hsn", "hsn_sac", "hsn", "sac", "hsn_code", "sac_code"),
        "default_rate": ("default_rate", "rate", "unit_rate", "price"),
        "gst_rate": ("gst_rate", "gst", "gst_%", "gst%", "gst_percent", "tax_rate"),
    },
    required=("name",),
    numeric=("default_rate", "gst_rate"),
    sample_header=("Item name", "Description", "Unit", "HSN/SAC", "Rate", "GST %"),
    sample_rows=(
        ("OPC 53 cement", "Portland cement, 50 kg bag", "bag", "2523", "380", "28"),
        ("River sand", "", "cft", "2505", "60", "5"),
        ("TMT steel bar 12 mm", "Fe 500D", "kg", "7214", "72.50", "18"),
    ),
)


@dataclass
class ItemImport:
    dry_run: bool
    items: list[CatalogItem]
    skipped_rows: list[int]
    ignored_columns: list[str]

    @property
    def count(self) -> int:
        return len(self.items)


def import_items(principal: Principal, data: bytes, *, dry_run: bool) -> ItemImport:
    from .serializers import CatalogItemWriteSerializer

    require(principal, "masters.edit")
    sheet = sheets.read(data, LAYOUT)
    existing = set(CatalogItem.objects.annotate(n=Lower("name")).values_list("n", flat=True))
    seen: dict[str, int] = {}

    def check(row: int, item: dict[str, Any]) -> RowErrors | None:
        key = str(item["name"]).strip().lower()
        if key in existing:
            return row_error(
                "name", "Your catalog already has an item with this name.", "item_exists"
            )
        if key in seen:
            return row_error("name", f"Also on row {seen[key]}.", "duplicate_name")
        seen[key] = row
        return None

    rows = validate_rows(sheet, CatalogItemWriteSerializer, check)
    items = [CatalogItem(**fields, tenant_id=principal.tenant_id) for _, fields in rows]
    if dry_run:
        for item in items:  # a preview: nothing was saved, so no id or timestamps
            item.id = item.created_at = item.updated_at = None
    else:
        with transaction.atomic():
            CatalogItem.objects.bulk_create(items)
    return ItemImport(dry_run, items, sheet.skipped_rows, sheet.ignored_columns)
