"""Reading GSTR-2B as the GST portal's Excel download (Returns, GSTR-2B,
Download, Excel), into the same Return as the JSON (reader.py).

The workbook has a "Read me" sheet with the GSTIN and the tax period
("Financial Year" 2026-27, "Tax Period" October) and a sheet per section:
B2B, B2BA, B2B-CDNR, B2B-CDNRA. Each section sheet has title rows, then a
two-row header ("Invoice details" over "Invoice number", "Invoice Date"...,
"Tax Amount" over "Integrated Tax(₹)"...). Columns are found by name (case,
spaces and symbols ignored), so the layout may shift a little between
portal versions. Amendment sheets carry the original and the revised
number: the first is the original, the last the one in force.

Safety as for every workbook (apps/core/sheets.py): openpyxl reads through
defusedxml, and the archive's uncompressed size is checked first.
"""

import io
import re
import zipfile
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.core.errors import Invalid
from apps.core.india import STATE_CODES
from apps.core.sheets import MAX_UNCOMPRESSED, _cell

from .reader import Doc, Return, _date

SECTIONS = {"b2b": "B2B", "b2ba": "B2BA", "b2bcdnr": "CDNR", "b2bcdnra": "CDNRA"}
MONTHS = {
    m: i
    for i, m in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ),
        start=1,
    )
}
STATE_BY_NAME = {re.sub(r"[^a-z]", "", n.lower()): c for c, n in STATE_CODES.items()}
ZERO = Decimal("0.00")


def _key(text: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def _money(text: str) -> Decimal:
    try:
        return Decimal(text.replace(",", "") or "0").quantize(Decimal("0.01"))
    except InvalidOperation:
        return ZERO


def _state(text: str) -> str:
    m = re.match(r"\s*(\d{1,2})", text)
    if m:
        return m.group(1).zfill(2)
    return STATE_BY_NAME.get(_key(text), "")


def _period(rows: list[list[str]]) -> tuple[str, date | None, date | None]:
    """GSTIN, the tax period and the date of generation from "Read me"."""
    found: dict[str, str] = {}
    for row in rows:
        for i, cell in enumerate(row[:-1]):
            k = _key(cell)
            value = next((v for v in row[i + 1 :] if v.strip()), "")
            if k in ("gstin", "financialyear", "taxperiod", "dateofgeneration") and value:
                found.setdefault(k, value.strip())
    month = MONTHS.get(found.get("taxperiod", "").strip().lower())
    fy = re.match(r"\s*(\d{4})", found.get("financialyear", ""))
    period = None
    if month and fy:
        start = int(fy.group(1))
        period = date(start if month >= 4 else start + 1, month, 1)
    generated = _date(found["dateofgeneration"]) if "dateofgeneration" in found else None
    return found.get("gstin", "").upper(), period, generated


def _header(rows: list[list[str]]) -> tuple[int, list[str]] | None:
    """The row with "GSTIN of supplier", merged with the row below it."""
    for n, row in enumerate(rows[:15]):
        if any(_key(c).startswith("gstinofsupplier") for c in row):
            below = rows[n + 1] if n + 1 < len(rows) else []
            names = [
                _key(below[i] if i < len(below) and below[i].strip() else top)
                for i, top in enumerate(row)
            ]
            return n + 2, names
    return None


def _find(names: list[str], *prefixes: str) -> list[int]:
    return [i for i, n in enumerate(names) if any(n.startswith(p) for p in prefixes)]


def _section(section: str, rows: list[list[str]], skipped: dict[str, int]) -> list[Doc]:
    found = _header(rows)
    if found is None:
        return []
    start, names = found
    gstin_col = _find(names, "gstinofsupplier")[0]
    name_col = next(iter(_find(names, "tradelegalname")), None)
    numbers = _find(names, "invoicenumber", "notenumber", "creditnotedebitnotenumber")
    dates = _find(names, "invoicedate", "notedate", "creditnotedebitnotedate")
    type_col = next(iter(_find(names, "notetype")), None)
    col = {
        k: next(iter(_find(names, p)), None)
        for k, p in (
            ("txval", "taxablevalue"),
            ("igst", "integratedtax"),
            ("cgst", "centraltax"),
            ("sgst", "stateuttax"),
            ("cess", "cess"),
            ("pos", "placeofsupply"),
            ("rev", "supplyattractreversecharge"),
            ("itc", "itcavailability"),
            ("reason", "reason"),
        )
    }
    if not numbers or not dates:
        return []

    def get(row: list[str], i: int | None) -> str:
        return row[i].strip() if i is not None and i < len(row) else ""

    docs: list[Doc] = []
    for row in rows[start:]:
        gstin = get(row, gstin_col).upper()
        if not re.fullmatch(r"[0-9]{2}[A-Z0-9]{13}", gstin):
            continue  # totals, notes, blank rows
        number, when = get(row, numbers[-1]), _date(get(row, dates[-1]))
        if not number or when is None:
            skipped["UNREADABLE"] = skipped.get("UNREADABLE", 0) + 1
            continue
        kind = get(row, type_col).lower()
        doc_type = (
            "INVOICE"
            if section in ("B2B", "B2BA")
            else ("DEBIT_NOTE" if "debit" in kind else "CREDIT_NOTE")
        )
        docs.append(
            Doc(
                section=section,
                doc_type=doc_type,
                supplier_gstin=gstin,
                supplier_name=get(row, name_col),
                number=number,
                original_number=get(row, numbers[0]) if len(numbers) > 1 else "",
                doc_date=when,
                taxable_value=_money(get(row, col["txval"])),
                igst=_money(get(row, col["igst"])),
                cgst=_money(get(row, col["cgst"])),
                sgst=_money(get(row, col["sgst"])),
                cess=_money(get(row, col["cess"])),
                place_of_supply=_state(get(row, col["pos"])),
                reverse_charge=get(row, col["rev"]).lower() in ("y", "yes"),
                itc_available=get(row, col["itc"]).lower() not in ("n", "no"),
                itc_reason=get(row, col["reason"]),
            )
        )
    return docs


def read(data: bytes) -> Return:
    import openpyxl

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(info.file_size for info in archive.infolist()) > MAX_UNCOMPRESSED:
                raise Invalid("file", "The workbook is too large.", code="file_too_large")
        book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
        raise Invalid(
            "file", "This is not a GSTR-2B download from the GST portal.", code="not_gstr2b"
        ) from exc
    try:
        sheets = {
            _key(ws.title): [[_cell(v) for v in row] for row in ws.iter_rows(values_only=True)]
            for ws in book.worksheets
        }
    finally:
        book.close()
    readme = next((rows for k, rows in sheets.items() if k.startswith("readme")), None)
    if readme is None:
        raise Invalid(
            "file", "This is not a GSTR-2B download from the GST portal.", code="not_gstr2b"
        )
    gstin, period, generated = _period(readme)
    if not gstin or period is None:
        raise Invalid(
            "file",
            "The GSTIN or the tax period is missing from the Read me sheet.",
            code="not_gstr2b",
        )
    docs: list[Doc] = []
    skipped: dict[str, int] = {}
    for key, section in SECTIONS.items():
        if key in sheets:
            docs += _section(section, sheets[key], skipped)
    return Return(gstin=gstin, period=period, generated_on=generated, docs=docs, skipped=skipped)
