"""Write a table (typed columns + rows) as CSV or XLSX bytes.

Text a user typed (names, descriptions) may start with `=`, `+`, `-` or `@`;
a spreadsheet would run it as a formula (CSV / formula injection). CSV text
cells starting so get a leading apostrophe; XLSX cells are stored as plain
strings, which spreadsheets never evaluate.
"""

import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

ColumnType = Literal["text", "money", "date", "int", "number"]  # number: quantities, %
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

CONTENT_TYPES = {
    "CSV": "text/csv; charset=utf-8",
    "XLSX": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "JSON": "application/json",
    "PDF": "application/pdf",
}
EXTENSIONS = {"CSV": "csv", "XLSX": "xlsx", "JSON": "json", "PDF": "pdf"}


@dataclass(frozen=True)
class Column:
    title: str
    type: ColumnType = "text"
    width: int = 14


@dataclass
class Table:
    name: str  # also the sheet name
    columns: list[Column]
    rows: list[list[Any]]


def _csv_value(value: Any, column: Column) -> str:
    if value is None:
        return ""
    if column.type == "money":
        return f"{Decimal(value):.2f}"
    if column.type == "number":
        return format(Decimal(value).normalize(), "f")
    if column.type == "date":
        return value.isoformat() if isinstance(value, date) else str(value)
    text = str(value)
    if column.type == "text" and text.startswith(FORMULA_PREFIXES):
        return "'" + text
    return text


def to_csv(table: Table) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([c.title for c in table.columns])
    for row in table.rows:
        writer.writerow(_csv_value(v, c) for v, c in zip(row, table.columns, strict=True))
    # BOM: Excel then reads UTF-8 (₹, Malayalam and Tamil names) correctly.
    return b"\xef\xbb\xbf" + out.getvalue().encode("utf-8")


def to_xlsx(table: Table) -> bytes:
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet(table.name[:31])
    for i, column in enumerate(table.columns, start=1):
        sheet.column_dimensions[get_column_letter(i)].width = column.width
    sheet.freeze_panes = "A2"
    header = []
    for column in table.columns:
        cell = WriteOnlyCell(sheet, value=column.title)
        cell.font = Font(bold=True)
        header.append(cell)
    sheet.append(header)
    for row in table.rows:
        cells = []
        for value, column in zip(row, table.columns, strict=True):
            cell = WriteOnlyCell(sheet, value=value)
            if value is None:
                pass
            elif column.type == "money":
                cell.number_format = "#,##0.00"
            elif column.type == "number":
                cell.number_format = "#,##0.###"
            elif column.type == "date":
                cell.number_format = "DD-MM-YYYY"
            elif column.type == "text":
                cell.data_type = "s"  # never a formula, whatever it starts with
            cells.append(cell)
        sheet.append(cells)
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def write(table: Table, file_format: str) -> bytes:
    return to_csv(table) if file_format == "CSV" else to_xlsx(table)
