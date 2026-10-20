"""Reading a BOQ spreadsheet (CSV or XLSX) into rows of strings.

The file type comes from the content, never the name. Columns are found by
header name (with common aliases), so column order and extra columns such as
"Amount" do not matter. Rows without unit, quantity and rate are headings or
subtotals and are skipped. Values stay strings: the same serializer as a
single `POST /boq-items` validates them.

XLSX safety: openpyxl parses through defusedxml (entity expansion and
external entities refused), and the archive's uncompressed size is checked
before anything is parsed (zip bombs).
"""

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from apps.core.errors import Invalid

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
MAX_UNCOMPRESSED = 50 * 1024 * 1024
HEADER_SEARCH_ROWS = 20  # title rows above the header are common

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
ALIASES = {alias: name for name, aliases in COLUMNS.items() for alias in aliases}


@dataclass
class Sheet:
    rows: list[tuple[int, dict[str, str]]] = field(default_factory=list)  # (row number, values)
    skipped_rows: list[int] = field(default_factory=list)
    ignored_columns: list[str] = field(default_factory=list)


def _normalise(header: str) -> str:
    """'Rate (₹)' -> 'rate', 'Item No.' -> 'item_no', 'GST %' -> 'gst_%'."""
    return re.sub(r"[^a-z0-9%]+", "_", header.strip().lower()).strip("_")


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):  # what Excel stores; repr is the shortest exact form
        return f"{Decimal(repr(value)):f}"
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value).strip()


def _clean_number(value: str) -> str:
    """Indian grouping and symbols people type: '₹ 1,23,456.50' -> '123456.50'."""
    return re.sub(r"[,\s₹%]", "", value)


def _raw_rows(data: bytes) -> list[list[str]]:
    if data[:4] == b"PK\x03\x04":
        return _xlsx_rows(data)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise Invalid("file", "Save the file as CSV UTF-8 or as .xlsx.", code="not_utf8") from None
    if "\x00" in text:
        raise Invalid("file", "Upload a CSV or .xlsx file.", code="unsupported_file")
    try:
        dialect: Any = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [[_cell(v) for v in row] for row in _limited(csv.reader(io.StringIO(text), dialect))]


def _xlsx_rows(data: bytes) -> list[list[str]]:
    import openpyxl

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(info.file_size for info in archive.infolist()) > MAX_UNCOMPRESSED:
                raise Invalid("file", "The workbook is too large.", code="file_too_large")
        book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
        raise Invalid("file", "Upload a CSV or .xlsx file.", code="unsupported_file") from exc
    try:
        sheet = book.worksheets[0]
        return [[_cell(v) for v in row] for row in _limited(sheet.iter_rows(values_only=True))]
    finally:
        book.close()


def _limited(rows: Any) -> list[Any]:
    out = []
    for row in rows:
        out.append(row)
        if len(out) > MAX_ROWS + HEADER_SEARCH_ROWS:
            raise Invalid("file", f"At most {MAX_ROWS} rows per import.", code="too_many_rows")
    return out


def _find_header(raw: list[list[str]]) -> tuple[int, list[str], list[str | None]]:
    """The first row (of the top 20) naming every required column."""
    for index, headers in enumerate(raw[:HEADER_SEARCH_ROWS]):
        names = [ALIASES.get(_normalise(h)) for h in headers]
        if set(REQUIRED) <= set(names):
            return index, headers, names
    raise Invalid(
        "file",
        "No header row found. Needed columns: " + ", ".join(REQUIRED) + ".",
        code="missing_columns",
    )


def read(data: bytes) -> Sheet:
    if len(data) > MAX_BYTES:
        raise Invalid("file", "At most 5 MB per import.", code="file_too_large")
    raw = _raw_rows(data)
    index, headers, names = _find_header(raw)
    columns: dict[str, int] = {}
    ignored = []
    for position, (name, header) in enumerate(zip(names, headers, strict=True)):
        if name is None or name in columns:
            if header:
                ignored.append(header)
            continue
        columns[name] = position

    sheet = Sheet(ignored_columns=ignored)
    for offset, cells in enumerate(raw[index + 1 :], start=index + 2):  # spreadsheet row number
        values = {name: (cells[i] if i < len(cells) else "") for name, i in columns.items()}
        if not any(values.values()):
            continue
        if not (values["unit"] or values["contract_qty"] or values["rate"]):
            sheet.skipped_rows.append(offset)  # a heading or subtotal row
            continue
        for name in NUMERIC:
            if values.get(name):
                values[name] = _clean_number(values[name])
        sheet.rows.append((offset, {k: v for k, v in values.items() if v != ""}))
    if len(sheet.rows) > MAX_ROWS:
        raise Invalid("file", f"At most {MAX_ROWS} rows per import.", code="too_many_rows")
    return sheet
