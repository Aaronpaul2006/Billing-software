"""Bill lines from a spreadsheet or from cells pasted out of Excel (B.7).

Nothing is saved: the lines come back checked, for the bill screen to add to
the draft, which then saves them as any other lines. Every row passes the
same line checks as a line typed on the screen; a row that fails is named
(`rows[3].rate`) and no line is returned.

Columns by name (description, quantity, unit, rate, discount, discount %,
GST %, HSN/SAC), or, for pasted cells without a header row, in this order:
description, quantity, unit, rate, GST %, HSN/SAC.
"""

from typing import Any

from apps.core import sheets
from apps.core.errors import Invalid
from apps.core.imports import RowErrors, row_error, validate_rows
from apps.core.permissions import require
from apps.core.tenancy import Principal

LAYOUT = sheets.Layout(
    columns={
        "description": ("description", "item", "particulars", "details", "work", "name"),
        "quantity": ("quantity", "qty", "nos"),
        "unit": ("unit", "uom", "units"),
        "rate": ("rate", "unit_rate", "price"),
        "discount_amount": ("discount", "discount_amount", "discount_rs", "disc"),
        "discount_pct": ("discount_%", "discount%", "discount_pct", "discount_percent", "disc_%"),
        "gst_rate": ("gst_rate", "gst", "gst_%", "gst%", "gst_percent", "tax_rate"),
        "sac_hsn": ("sac_hsn", "hsn_sac", "hsn", "sac", "hsn_code", "sac_code"),
    },
    required=("description", "quantity"),
    numeric=("quantity", "rate", "discount_amount", "discount_pct", "gst_rate"),
    # a heading or total row: no quantity
    is_heading=lambda v: not v.get("quantity"),
    sample_header=("Description", "Quantity", "Unit", "Rate", "Discount %", "GST %", "HSN/SAC"),
    sample_rows=(
        ("Excavation in ordinary soil", "120", "cum", "450", "", "18", "9954"),
        ("PCC 1:4:8 below footings", "18.5", "cum", "6200", "5", "18", "9954"),
    ),
)

# Pasted cells without a header row are read in this order.
PASTE_ORDER = ("description", "quantity", "unit", "rate", "gst_rate", "sac_hsn")
MAX_LINES = 500


def _with_header(raw: list[list[str]]) -> list[list[str]]:
    """Cells without a header row get the paste order as their header."""
    try:
        sheets.rows_of(raw, LAYOUT)
    except Invalid as exc:
        if exc.code != "missing_columns":
            raise
        return [list(PASTE_ORDER), *raw]
    return raw


def parse_lines(
    principal: Principal, *, data: bytes | None = None, text: str | None = None
) -> tuple[list[dict[str, Any]], sheets.Sheet]:
    from ..serializers import LineInSerializer

    require(principal, "documents.draft")
    raw = sheets.raw_rows(data) if data is not None else sheets.text_rows(text or "")
    sheet = sheets.rows_of(_with_header(raw), LAYOUT)
    if len(sheet.rows) > MAX_LINES:
        raise Invalid("file", f"At most {MAX_LINES} lines at a time.", code="too_many_rows")

    def check(row: int, line: dict[str, Any]) -> RowErrors | None:
        if line.get("rate") is None:  # no catalog / BOQ item to take it from
            return row_error("rate", "A rate is required.", "required")
        return None

    rows = validate_rows(sheet, LineInSerializer, check)
    return [line for _, line in rows], sheet
