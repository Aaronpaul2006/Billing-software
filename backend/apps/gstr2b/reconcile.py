"""Matching a GSTR-2B with the books (Part B). Worked out each time it is
read, so recording a missing bill moves it to "matched" at once.

The books: recorded vendor bills and expenses with GST from a supplier whose
GSTIN we have. A 2B invoice (or debit note) is matched to the same
supplier's document

1. with the same number, read loosely: case, spaces and "/ - ." do not count,
   nor leading zeros ("KST/0101" is "kst-101"); else
2. of the same value and tax (to the rupee) dated within 3 days, when the
   numbers are written differently ("KST/101/26-27" and "101").

Matched with value and tax equal to the rupee: MATCHED; otherwise
AMOUNTS_DIFFER, with the differences. A 2B document not found: NOT_IN_BOOKS
(credit notes always, as the books have none from suppliers). A document in
the books dated in the 2B's month and not found: NOT_IN_2B: the supplier has
not reported it, so its input tax credit is at risk.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from apps.expenses.models import Expense
from apps.payables.models import VendorBill

from .models import Gstr2bLine, Gstr2bReturn

RUPEE = Decimal("1.00")
DAYS = timedelta(days=3)
ZERO = Decimal("0.00")


def number_key(number: str) -> str:
    """'KST/0101' and 'kst-101' -> 'KST101'."""
    plain = re.sub(r"[^A-Z0-9]", "", number.upper())
    return re.sub(r"(?<![0-9])0+(?=[0-9])", "", plain)


@dataclass
class BookDoc:
    kind: str  # VENDOR_BILL or EXPENSE
    id: uuid.UUID
    supplier_gstin: str
    supplier_name: str
    number: str
    doc_date: date
    taxable_value: Decimal
    tax: Decimal
    itc_eligible: bool


@dataclass
class Row:
    status: str  # MATCHED, AMOUNTS_DIFFER, NOT_IN_BOOKS, NOT_IN_2B
    line: Gstr2bLine | None = None
    book: BookDoc | None = None
    taxable_difference: Decimal = ZERO  # 2B less books
    tax_difference: Decimal = ZERO
    note: str = ""


@dataclass
class Result:
    gst_return: Gstr2bReturn
    rows: list[Row]
    counts: dict[str, int] = field(default_factory=dict)
    itc_in_2b: Decimal = ZERO  # available ITC the portal shows (notes taken off)
    itc_matched: Decimal = ZERO
    itc_not_in_books: Decimal = ZERO  # in the 2B, not in our books
    itc_at_risk: Decimal = ZERO  # claimed in our books, not in the 2B


def line_tax(line: Gstr2bLine) -> Decimal:
    return line.igst + line.cgst + line.sgst + line.cess


def book_docs() -> list[BookDoc]:
    docs = [
        BookDoc(
            "VENDOR_BILL",
            b.pk,
            (b.vendor_party.gstin or "").upper(),
            b.vendor_party.display_name,
            b.bill_number,
            b.bill_date,
            b.taxable_value,
            b.gst_amount,
            b.itc_eligible,
        )
        for b in VendorBill.objects.filter(
            status="RECORDED", gst_amount__gt=0, vendor_party__gstin__isnull=False
        ).select_related("vendor_party")
    ]
    docs += [
        BookDoc(
            "EXPENSE",
            e.pk,
            (e.vendor_party.gstin or "").upper(),
            e.vendor_party.display_name,
            e.vendor_bill_number or "",
            e.expense_date,
            e.taxable_value,
            e.gst_amount,
            e.itc_eligible,
        )
        for e in Expense.objects.filter(
            status="RECORDED", gst_amount__gt=0, vendor_party__gstin__isnull=False
        ).select_related("vendor_party")
        if e.vendor_party is not None
    ]
    return docs


def _close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= RUPEE


def reconcile(gst_return: Gstr2bReturn) -> Result:
    lines = list(
        Gstr2bLine.objects.filter(gst_return=gst_return).order_by("supplier_name", "doc_date")
    )
    pool: dict[str, list[BookDoc]] = {}
    for doc in book_docs():
        pool.setdefault(doc.supplier_gstin, []).append(doc)
    rows: list[Row] = []
    used: set[uuid.UUID] = set()

    def take(doc: BookDoc) -> BookDoc:
        used.add(doc.id)
        return doc

    for line in lines:
        tax = line_tax(line)
        if line.doc_type == "CREDIT_NOTE":
            rows.append(
                Row("NOT_IN_BOOKS", line=line, note="A credit note from the supplier: less ITC.")
            )
            continue
        candidates = [d for d in pool.get(line.supplier_gstin, []) if d.id not in used]
        key = number_key(line.doc_number)
        found = next((d for d in candidates if number_key(d.number) == key), None)
        note = ""
        if found is None:
            found = next(
                (
                    d
                    for d in candidates
                    if _close(d.taxable_value, line.taxable_value)
                    and _close(d.tax, tax)
                    and abs(d.doc_date - line.doc_date) <= DAYS
                ),
                None,
            )
            if found is not None:
                note = f"Numbers differ: theirs {line.doc_number}, ours {found.number}."
        if found is None:
            rows.append(Row("NOT_IN_BOOKS", line=line))
            continue
        take(found)
        same = _close(found.taxable_value, line.taxable_value) and _close(found.tax, tax)
        rows.append(
            Row(
                "MATCHED" if same else "AMOUNTS_DIFFER",
                line=line,
                book=found,
                taxable_difference=line.taxable_value - found.taxable_value,
                tax_difference=tax - found.tax,
                note=note,
            )
        )

    month = gst_return.period
    next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    for docs in pool.values():
        for doc in docs:
            if doc.id not in used and month <= doc.doc_date < next_month:
                note = "" if doc.itc_eligible else "No ITC claimed on it in the books."
                rows.append(Row("NOT_IN_2B", book=doc, note=note))

    result = Result(gst_return, rows)
    for row in rows:
        result.counts[row.status] = result.counts.get(row.status, 0) + 1
        line = row.line
        if line is not None and line.itc_available and not line.reverse_charge:
            sign = -1 if line.doc_type == "CREDIT_NOTE" else 1
            result.itc_in_2b += sign * line_tax(line)
            if row.status == "MATCHED":
                result.itc_matched += line_tax(line)
            if row.status == "NOT_IN_BOOKS" and line.doc_type != "CREDIT_NOTE":
                result.itc_not_in_books += line_tax(line)
        if row.status == "NOT_IN_2B" and row.book is not None and row.book.itc_eligible:
            result.itc_at_risk += row.book.tax
    return result
