"""Reading a spreadsheet (CSV or XLSX) into rows of strings, for every import
(BOQ items, catalog items, clients, bill lines) and writing their sample files.

The file type comes from the content, never the name. Columns are found by
header name (with common aliases, case and punctuation ignored), so column
order and extra columns do not matter. Values stay strings: the same
serializer as a single create validates them, row by row.

XLSX safety: openpyxl parses through defusedxml (entity expansion and
external entities refused), and the archive's uncompressed size is checked
before anything is parsed (zip bombs).
"""

import csv
import io
import re
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .errors import Invalid

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
MAX_UNCOMPRESSED = 50 * 1024 * 1024
HEADER_SEARCH_ROWS = 20  # title rows above the header are common


@dataclass(frozen=True)
class Layout:
    """What a kind of import expects. `columns`: field -> header aliases
    (normalised: lower case, `_` for spaces and punctuation, `%` kept)."""

    columns: dict[str, tuple[str, ...]]
    required: tuple[str, ...]
    numeric: tuple[str, ...] = ()
    # A row with values that is still not data (a heading or subtotal): skipped.
    is_heading: Callable[[dict[str, str]], bool] | None = None
    # The sample file: its header row (one name per field, in order) and rows.
    sample_header: tuple[str, ...] = ()
    sample_rows: tuple[tuple[str, ...], ...] = ()

    def aliases(self) -> dict[str, str]:
        return {alias: name for name, aliases in self.columns.items() for alias in aliases}


@dataclass
class Sheet:
    rows: list[tuple[int, dict[str, str]]] = field(default_factory=list)  # (row number, values)
    skipped_rows: list[int] = field(default_factory=list)
    ignored_columns: list[str] = field(default_factory=list)


def normalise(header: str) -> str:
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


def clean_number(value: str) -> str:
    """Indian grouping and symbols people type: '₹ 1,23,456.50' -> '123456.50'."""
    return re.sub(r"[,\s₹%]", "", value)


def raw_rows(data: bytes) -> list[list[str]]:
    """Every row of the file (CSV or the first sheet of an .xlsx) as strings."""
    if len(data) > MAX_BYTES:
        raise Invalid("file", "At most 5 MB per import.", code="file_too_large")
    if data[:4] == b"PK\x03\x04":
        return _xlsx_rows(data)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise Invalid("file", "Save the file as CSV UTF-8 or as .xlsx.", code="not_utf8") from None
    if "\x00" in text:
        raise Invalid("file", "Upload a CSV or .xlsx file.", code="unsupported_file")
    return text_rows(text)


def text_rows(text: str) -> list[list[str]]:
    """Rows of delimited text: CSV, or cells copied from a spreadsheet (tabs)."""
    try:
        dialect: Any = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel_tab if "\t" in text else csv.excel
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


def _find_header(raw: list[list[str]], layout: Layout) -> tuple[int, list[str], list[str | None]]:
    """The first row (of the top 20) naming every required column."""
    aliases = layout.aliases()
    for index, headers in enumerate(raw[:HEADER_SEARCH_ROWS]):
        names = [aliases.get(normalise(h)) for h in headers]
        if set(layout.required) <= set(names):
            return index, headers, names
    raise Invalid(
        "file",
        "No header row found. Needed columns: " + ", ".join(layout.required) + ".",
        code="missing_columns",
    )


def rows_of(raw: list[list[str]], layout: Layout) -> Sheet:
    """Data rows under the header row, by field name; empty values left out."""
    index, headers, names = _find_header(raw, layout)
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
        if layout.is_heading is not None and layout.is_heading(values):
            sheet.skipped_rows.append(offset)
            continue
        for name in layout.numeric:
            if values.get(name):
                values[name] = clean_number(values[name])
        sheet.rows.append((offset, {k: v for k, v in values.items() if v != ""}))
    if len(sheet.rows) > MAX_ROWS:
        raise Invalid("file", f"At most {MAX_ROWS} rows per import.", code="too_many_rows")
    return sheet


def read(data: bytes, layout: Layout) -> Sheet:
    return rows_of(raw_rows(data), layout)


# --- sample files ------------------------------------------------------------------------

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def sample(layout: Layout, fmt: str) -> tuple[bytes, str]:
    """The layout's sample as (content, content type): fmt "xlsx" or "csv"."""
    rows: Sequence[Sequence[str]] = [layout.sample_header, *layout.sample_rows]
    if fmt == "csv":
        out = io.StringIO()
        csv.writer(out, lineterminator="\r\n").writerows(rows)
        return ("﻿" + out.getvalue()).encode("utf-8"), "text/csv; charset=utf-8"
    import openpyxl
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    book = openpyxl.Workbook()
    sheet = book.active
    assert sheet is not None  # noqa: S101 - a new workbook always has its sheet
    for row in rows:
        sheet.append(list(row))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for column, header in enumerate(layout.sample_header, start=1):
        sheet.column_dimensions[get_column_letter(column)].width = max(12, len(header) + 4)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue(), XLSX
