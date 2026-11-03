"""The BOQ spreadsheet layout (CSV or XLSX), read by apps.core.sheets.

Columns are found by header name (with common aliases), so column order and
extra columns such as "Amount" do not matter. Rows without unit, quantity and
rate are headings or subtotals and are skipped. Values stay strings: the same
serializer as a single `POST /boq-items` validates them.
"""

from apps.core import sheets
from apps.core.sheets import MAX_BYTES, Sheet

__all__ = ["LAYOUT", "MAX_BYTES", "Sheet", "read"]

COLUMNS: dict[str, tuple[str, ...]] = {
    "item_code": ("item_code", "code", "item_no", "item_number", "item"),
    "description": ("description", "item_description", "particulars", "description_of_item"),
    "unit": ("unit", "uom", "units"),
    "contract_qty": ("contract_qty", "qty", "quantity"),
    "rate": ("rate", "unit_rate"),
    "gst_rate": ("gst_rate", "gst", "gst_%", "gst_percent"),
    "sac_hsn": ("sac_hsn", "hsn_sac", "sac", "hsn", "sac_code", "hsn_code"),
    "is_variation": ("is_variation", "variation"),
    "sort_order": ("sort_order",),
}
REQUIRED = ("item_code", "description", "unit", "contract_qty", "rate")
NUMERIC = ("contract_qty", "rate", "gst_rate", "sort_order")

LAYOUT = sheets.Layout(
    columns=COLUMNS,
    required=REQUIRED,
    numeric=NUMERIC,
    # no unit, quantity or rate: a heading or subtotal row
    is_heading=lambda v: not (v["unit"] or v["contract_qty"] or v["rate"]),
    sample_header=("Item No.", "Description", "Unit", "Qty", "Rate", "GST %", "HSN/SAC"),
    sample_rows=(
        ("1", "Earthwork", "", "", "", "", ""),
        ("1.1", "Excavation in ordinary soil", "cum", "120", "450", "18", "9954"),
        ("1.2", "PCC 1:4:8 below footings", "cum", "18.5", "6200", "18", "9954"),
    ),
)


def read(data: bytes) -> Sheet:
    return sheets.read(data, LAYOUT)
