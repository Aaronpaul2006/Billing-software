"""What each export contains: a table of typed columns and rows, a file name
stem and warnings. Called inside the requesting tenant's context, so RLS and
the tenant manager both apply. Amounts stay Decimal until the writer."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import OuterRef, Subquery, Sum
from django.utils import timezone

from apps.core.india import place_name
from apps.documents.models import Document
from apps.documents.pdf.render import TITLES
from apps.expenses.models import Expense
from apps.payments.models import Allocation, Payment
from apps.reports import queries

from .writers import Column, Table

MAX_ROWS = 100_000

MODES = {
    "BANK_TRANSFER": "Bank transfer",
    "UPI": "UPI",
    "CHEQUE": "Cheque",
    "CASH": "Cash",
    "CARD": "Card",
    "OTHER": "Other",
}


class TooManyRows(Exception):
    pass


@dataclass
class Built:
    table: Table
    stem: str  # file name without extension
    warnings: list[str] = field(default_factory=list)


def _date_range(params: dict[str, Any]) -> tuple[date, date]:
    return date.fromisoformat(params["from"]), date.fromisoformat(params["to"])


def _check_size(count: int) -> None:
    if count > MAX_ROWS:
        raise TooManyRows(f"More than {MAX_ROWS:,} rows: choose a shorter period.")


def _label(value: str) -> str:
    return value.replace("_", " ").capitalize()


def _state(code: str | None) -> str | None:
    return f"{code} {place_name(code)}".strip() if code else None


def documents(tenant_id: uuid.UUID, params: dict[str, Any]) -> Built:
    """Invoice register: every issued (or cancelled) document in the period."""
    start, end = _date_range(params)
    queryset = (
        Document.objects.filter(doc_date__range=(start, end))
        .exclude(status="DRAFT")
        .select_related("project")
        .order_by("doc_date", "doc_number", "created_at")
    )
    if params.get("book") == "GST":
        queryset = queryset.filter(is_gst_document=True)
    elif params.get("book") == "NON_GST":
        queryset = queryset.filter(is_gst_document=False)
    _check_size(queryset.count())
    columns = [
        Column("Date", "date", 12),
        Column("Number", width=14),
        Column("Type", width=16),
        Column("Status", width=11),
        Column("Client", width=30),
        Column("Client GSTIN", width=17),
        Column("Project", width=24),
        Column("Place of supply", width=18),
        Column("Taxable value", "money"),
        Column("CGST", "money", 12),
        Column("SGST", "money", 12),
        Column("IGST", "money", 12),
        Column("Cess", "money", 10),
        Column("Round off", "money", 10),
        Column("Total", "money"),
        Column("Retention", "money", 12),
        Column("Income-tax TDS", "money", 12),
        Column("GST TDS", "money", 12),
        Column("Advance recovered", "money", 12),
        Column("Net receivable", "money"),
        Column("Settled", "money"),
        Column("Outstanding", "money"),
        Column("Cancel reason", width=24),
    ]
    rows = []
    for d in queryset:
        party = d.party_snapshot or {}
        revenue = d.doc_type not in ("QUOTATION", "PROFORMA")
        if not revenue:
            outstanding = None
        elif d.status == "CANCELLED":
            outstanding = Decimal("0.00")
        else:
            outstanding = d.net_receivable - d.amount_settled
        rows.append(
            [
                d.doc_date,
                d.doc_number,
                TITLES.get(d.doc_type, d.doc_type),
                _label(d.status),
                party.get("display_name") or party.get("legal_name"),
                party.get("gstin"),
                d.project.name if d.project else None,
                _state(d.place_of_supply),
                d.subtotal,
                d.cgst_amount,
                d.sgst_amount,
                d.igst_amount,
                d.cess_amount,
                d.round_off,
                d.grand_total,
                d.retention_amount,
                d.income_tax_tds_amount,
                d.gst_tds_amount,
                d.advance_recovery_amount,
                d.net_receivable,
                d.amount_settled if revenue else None,
                outstanding,
                d.cancel_reason,
            ]
        )
    warnings = []
    if any(r[2] == TITLES["CREDIT_NOTE"] for r in rows):
        warnings.append("Credit notes are listed with positive amounts: subtract them in totals.")
    return Built(
        Table("Invoice register", columns, rows), f"invoice-register_{start}_{end}", warnings
    )


def payments(tenant_id: uuid.UUID, params: dict[str, Any]) -> Built:
    start, end = _date_range(params)
    allocated = (
        Allocation.objects.filter(payment_id=OuterRef("pk"))
        .values("payment_id")
        .annotate(total=Sum("amount"))
        .values("total")
    )
    queryset = (
        Payment.objects.filter(payment_date__range=(start, end))
        .select_related("party", "project")
        .annotate(allocated=Subquery(allocated))
        .order_by("payment_date", "created_at")
    )
    _check_size(queryset.count())
    columns = [
        Column("Date", "date", 12),
        Column("Client", width=30),
        Column("Project", width=24),
        Column("Mode", width=14),
        Column("Reference", width=20),
        Column("Amount", "money"),
        Column("Allocated", "money"),
        Column("Unallocated", "money"),
        Column("Status", width=10),
        Column("Void reason", width=24),
    ]
    rows = []
    for p in queryset:
        allocated_amount = p.allocated or Decimal("0.00")
        rows.append(
            [
                p.payment_date,
                p.party.display_name,
                p.project.name if p.project else None,
                MODES.get(p.mode, p.mode),
                p.reference,
                p.amount,
                allocated_amount,
                p.amount - allocated_amount if p.status == "RECORDED" else Decimal("0.00"),
                _label(p.status),
                p.void_reason,
            ]
        )
    return Built(Table("Payments", columns, rows), f"payments_{start}_{end}")


def expenses(tenant_id: uuid.UUID, params: dict[str, Any]) -> Built:
    start, end = _date_range(params)
    queryset = (
        Expense.objects.filter(expense_date__range=(start, end))
        .select_related("vendor_party", "project")
        .order_by("expense_date", "created_at")
    )
    _check_size(queryset.count())
    columns = [
        Column("Date", "date", 12),
        Column("Category", width=14),
        Column("Description", width=36),
        Column("Vendor", width=26),
        Column("Vendor bill number", width=16),
        Column("Project", width=24),
        Column("Amount before GST", "money"),
        Column("GST", "money", 12),
        Column("ITC claimable", width=8),
        Column("Total", "money"),
        Column("Paid", "money"),
        Column("Balance", "money"),
        Column("Paid by", width=14),
        Column("Status", width=10),
    ]
    rows = [
        [
            x.expense_date,
            _label(x.category),
            x.description,
            x.vendor_party.display_name if x.vendor_party else None,
            x.vendor_bill_number,
            x.project.name if x.project else None,
            x.taxable_value,
            x.gst_amount,
            "Yes" if x.itc_eligible else "No",
            x.total_amount,
            x.amount_paid,
            x.total_amount - x.amount_paid,
            MODES.get(x.payment_mode, x.payment_mode) if x.payment_mode else None,
            _label(x.status),
        ]
        for x in queryset
    ]
    return Built(Table("Expenses", columns, rows), f"expenses_{start}_{end}")


def receivables(tenant_id: uuid.UUID, params: dict[str, Any]) -> Built:
    """What clients owe now, by age (the dashboard's receivables report)."""
    book = params.get("book", "ALL")
    columns = [
        Column("Client", width=32),
        Column("Documents", "int", 10),
        Column("Not due", "money"),
        Column("1-30 days", "money"),
        Column("31-60 days", "money"),
        Column("61-90 days", "money"),
        Column("Over 90 days", "money"),
        Column("Total", "money"),
    ]
    rows = [
        [
            r["display_name"],
            r["document_count"],
            r["bucket_not_due"],
            r["bucket_1_30"],
            r["bucket_31_60"],
            r["bucket_61_90"],
            r["bucket_90_plus"],
            r["total"],
        ]
        for r in queries.receivables(tenant_id, book)
    ]
    return Built(Table("Receivables", columns, rows), f"receivables_{timezone.localdate()}")


BUILDERS: dict[str, Callable[[uuid.UUID, dict[str, Any]], Built]] = {
    "DOCUMENTS": documents,
    "PAYMENTS": payments,
    "EXPENSES": expenses,
    "RECEIVABLES": receivables,
}
