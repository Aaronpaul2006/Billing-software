"""Cash-flow forecast (Part B): the next weeks' money in and out, as ranges.

Money in: client bills and retention releases still owed (v_receivables), in
the week they fall due (the due date, or the bill's date when it has none).
Money out: vendor bills and released subcontractor retention still to pay,
the same way. Bills already past due have no honest week, so they make the
range: the low balance assumes overdue client bills do not come in within the
forecast but overdue vendor bills are paid now; the high balance assumes both
are settled in the first week. Cash today is the last balance on each
imported bank statement, when there is one.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import F

from apps.banking.models import BankLine
from apps.payables.models import VendorBill, VendorRetentionRelease

from .queries import _rows

ZERO = Decimal("0.00")


@dataclass
class Item:
    id: Any
    kind: str
    number: str
    party_name: str
    due_date: date
    outstanding: Decimal


@dataclass
class Week:
    start: date
    end: date
    money_in: Decimal = ZERO
    money_out: Decimal = ZERO
    bills_in: list[Item] = field(default_factory=list)
    bills_out: list[Item] = field(default_factory=list)
    balance_low: Decimal = ZERO
    balance_high: Decimal = ZERO


def _cash_today() -> tuple[Decimal | None, list[str]]:
    """The last balance on each account's statement (the newest line with one)."""
    total, sources = ZERO, []
    for account in BankLine.objects.values_list("account_label", flat=True).distinct():
        last = (
            BankLine.objects.filter(account_label=account, balance__isnull=False)
            .order_by("-line_date", "-id")
            .first()
        )
        if last and last.balance is not None:
            total += last.balance
            sources.append(f"{account} on {last.line_date:%d %b %Y}")
    return (total if sources else None), sorted(sources)


def forecast(tenant: uuid.UUID, today: date, weeks: int) -> dict[str, Any]:
    monday = today - timedelta(days=today.weekday())
    span = [
        Week(monday + timedelta(weeks=i), monday + timedelta(weeks=i, days=6)) for i in range(weeks)
    ]
    last_day = span[-1].end
    overdue_in = overdue_out = ZERO

    for r in _rows(
        """SELECT coalesce(d.document_id, d.retention_release_id) AS id, d.doc_type,
                  d.doc_number, p.display_name, coalesce(d.due_date, d.doc_date) AS due,
                  d.outstanding
             FROM v_receivables d
             JOIN parties p ON p.tenant_id = d.tenant_id AND p.id = d.party_id
            WHERE d.tenant_id = %s""",
        [tenant],
    ):
        due, owed = r["due"], r["outstanding"]
        if due < today:
            overdue_in += owed
        elif due <= last_day:
            w = span[(due - monday).days // 7]
            w.money_in += owed
            kind = "RETENTION_RELEASE" if r["doc_type"] == "RETENTION_RELEASE" else "BILL"
            w.bills_in.append(
                Item(r["id"], kind, r["doc_number"] or "", r["display_name"], due, owed)
            )

    for b in VendorBill.objects.filter(
        status="RECORDED", amount_paid__lt=F("net_payable")
    ).select_related("vendor_party"):
        due = b.due_date or b.bill_date
        owed = b.net_payable - b.amount_paid
        if due < today:
            overdue_out += owed
        elif due <= last_day:
            w = span[(due - monday).days // 7]
            w.money_out += owed
            w.bills_out.append(
                Item(b.pk, "VENDOR_BILL", b.bill_number, b.vendor_party.display_name, due, owed)
            )

    for rel in VendorRetentionRelease.objects.filter(
        status="RELEASED", amount_paid__lt=F("amount")
    ).select_related("vendor_party", "work_order"):
        due = rel.due_date or rel.release_date
        owed = rel.amount - rel.amount_paid
        if due < today:
            overdue_out += owed
        elif due <= last_day:
            w = span[(due - monday).days // 7]
            w.money_out += owed
            number = f"Retention, {rel.work_order.wo_number}"
            name = rel.vendor_party.display_name
            w.bills_out.append(Item(rel.pk, "RETENTION_OUT", number, name, due, owed))

    cash, sources = _cash_today()
    start = cash if cash is not None else ZERO
    low = start - overdue_out  # pay what is overdue now; nothing overdue comes in
    high = start + overdue_in - overdue_out  # ...and everything overdue comes in now
    for w in span:
        w.bills_in.sort(key=lambda i: i.due_date)
        w.bills_out.sort(key=lambda i: i.due_date)
        low += w.money_in - w.money_out
        high += w.money_in - w.money_out
        w.balance_low, w.balance_high = low, high

    lowest = min(span, key=lambda w: w.balance_low)
    return {
        "as_of": today,
        "cash_today": cash,
        "cash_sources": sources,
        "overdue_in": overdue_in,
        "overdue_out": overdue_out,
        "weeks": span,
        "lowest_week_start": lowest.start,
        "lowest_balance": lowest.balance_low,
    }
