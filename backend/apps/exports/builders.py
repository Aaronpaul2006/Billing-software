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
from django.utils.text import slugify

from apps.core.india import place_name
from apps.documents.models import Document
from apps.documents.pdf.render import TITLES
from apps.expenses.models import Expense
from apps.parties.models import Party
from apps.payments.models import Allocation, Payment
from apps.projects.models import Project
from apps.projects.services import boq_progress_rows
from apps.reports import queries
from apps.reports.statement import build_statement

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


def boq(tenant_id: uuid.UUID, params: dict[str, Any]) -> Built:
    """One project's BOQ: what was contracted, billed so far, and what is left."""
    project = Project.objects.get(pk=params["project_id"])
    progress = boq_progress_rows(project)
    columns = [
        Column("Item code", width=12),
        Column("Description", width=40),
        Column("Unit", width=8),
        Column("Rate", "money"),
        Column("Contract qty", "number", 12),
        Column("Billed qty", "number", 12),
        Column("Balance qty", "number", 12),
        Column("Contract value", "money"),
        Column("Billed value", "money"),
        Column("Progress %", "number", 10),
        Column("Variation", width=9),
    ]
    rows = [
        [
            r["item_code"],
            r["description"],
            r["unit"],
            r["rate"],
            r["contract_qty"],
            r["billed_qty"],
            r["balance_qty"],
            r["contract_value"],
            r["billed_value"],
            r["progress_pct"],
            "Yes" if r["is_variation"] else "No",
        ]
        for r in progress["results"]
    ]
    _check_size(len(rows))
    stem = f"boq_{project.code}_{timezone.localdate()}".replace("/", "-")
    return Built(Table("BOQ", columns, rows), stem)


def projects(tenant_id: uuid.UUID, params: dict[str, Any]) -> Built:
    """The project margins report: billing, deductions, cost and margin."""
    columns = [
        Column("Code", width=12),
        Column("Project", width=30),
        Column("Contract value", "money"),
        Column("Billed (before GST)", "money"),
        Column("Retention held", "money"),
        Column("Retention released", "money"),
        Column("TDS deducted", "money"),
        Column("Advance recovered", "money"),
        Column("Outstanding", "money"),
        Column("Cost", "money"),
        Column("Margin", "money"),
    ]
    rows = [
        [
            r["code"],
            r["name"],
            r["contract_value"],
            r["billed_taxable"],
            r["retention_held"],
            r["retention_released"],
            r["tds_deducted"],
            r["advance_recovered"],
            r["outstanding"],
            r["cost"],
            r["margin"],
        ]
        for r in queries.projects(tenant_id)
    ]
    return Built(Table("Projects", columns, rows), f"project-margins_{timezone.localdate()}")


STATEMENT_KINDS = {
    "TAX_INVOICE": "Tax invoice",
    "BILL_OF_SUPPLY": "Bill of supply",
    "DEBIT_NOTE": "Debit note",
    "CREDIT_NOTE": "Credit note",
    "RETENTION_RELEASE": "Retention release",
    "PAYMENT": "Payment",
}


def statement_stem(party: Party, params: dict[str, Any]) -> str:
    name = slugify(party.display_name)[:40] or "client"
    return f"statement_{name}_{params['from']}_{params['to']}"


def statement(tenant_id: uuid.UUID, params: dict[str, Any]) -> Built:
    """A client's statement of account, opening and closing balance as rows."""
    party = Party.objects.get(pk=params["party_id"])
    start, end = _date_range(params)
    s = build_statement(tenant_id, party.pk, start, end)
    columns = [
        Column("Date", "date", 11),
        Column("Type", width=16),
        Column("Reference", width=16),
        Column("Description", width=56),
        Column("Debit", "money"),
        Column("Credit", "money"),
        Column("Balance", "money"),
    ]
    rows: list[list[Any]] = [[start, "", "", "Opening balance", None, None, s["opening_balance"]]]
    rows += [
        [
            e["date"],
            STATEMENT_KINDS[e["kind"]],
            e["reference"],
            e["description"],
            e["debit"] or None,
            e["credit"] or None,
            e["balance"],
        ]
        for e in s["entries"]
    ]
    rows.append(
        [end, "", "", "Closing balance", s["total_debit"], s["total_credit"], s["closing_balance"]]
    )
    _check_size(len(rows))
    return Built(Table("Statement", columns, rows), statement_stem(party, params))


def tds_deducted(tenant_id: uuid.UUID, params: dict[str, Any]) -> Built:
    """TDS we deducted on vendor bills (payables, Part B): one row per bill, by
    the month it was credited (the bill date), for paying it by the 7th and the
    26Q return. Voided bills are left out."""
    from apps.payables.models import VendorBill  # payables come after exports

    start, end = _date_range(params)
    queryset = (
        VendorBill.objects.filter(
            bill_date__range=(start, end), status="RECORDED", tds_amount__gt=0
        )
        .select_related("vendor_party")
        .order_by("bill_date", "created_at")
    )
    _check_size(queryset.count())
    columns = [
        Column("Month", width=10),
        Column("Bill date", "date", 12),
        Column("Vendor", width=28),
        Column("Vendor PAN", width=12),
        Column("Section", width=8),
        Column("Vendor bill number", width=18),
        Column("Amount before GST", "money"),
        Column("Rate %", "money", 8),
        Column("TDS deducted", "money"),
    ]
    rows: list[list[Any]] = [
        [
            f"{b.bill_date:%b %Y}",
            b.bill_date,
            b.vendor_party.display_name,
            b.vendor_party.pan,
            b.tds_section,
            b.bill_number,
            b.taxable_value,
            b.tds_rate,
            b.tds_amount,
        ]
        for b in queryset
    ]
    if rows:
        rows.append(
            [
                "",
                None,
                "Total",
                None,
                None,
                None,
                sum(r[6] for r in rows),
                None,
                sum(r[8] for r in rows),
            ]
        )
    return Built(Table("TDS deducted", columns, rows), f"tds_deducted_{start}_{end}")


BUILDERS: dict[str, Callable[[uuid.UUID, dict[str, Any]], Built]] = {
    "DOCUMENTS": documents,
    "PAYMENTS": payments,
    "EXPENSES": expenses,
    "RECEIVABLES": receivables,
    "BOQ": boq,
    "PROJECTS": projects,
    "STATEMENT": statement,
    "TDS_DEDUCTED": tds_deducted,
}
