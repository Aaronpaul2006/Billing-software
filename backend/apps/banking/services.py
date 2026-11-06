"""Bank statements (Part B): import the bank's file, then match each line to
what it is. Nothing is matched or recorded without a person choosing it; the
suggestions only rank what fits (same amount, near the date, the UTR or the
party's name in the narration)."""

import re
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import F

from apps.core.errors import Conflict, Invalid
from apps.core.permissions import require
from apps.core.queries import get_or_404, get_or_invalid
from apps.core.tenancy import Principal
from apps.core.versioning import update_versioned
from apps.documents.models import Document
from apps.payables import services as payables
from apps.payables.models import VendorBill, VendorPayment
from apps.payments import services as payments
from apps.payments.models import Payment

from . import statement
from .models import BankLine

RECORD = "payments.record"
NEAR_DAYS = 10
RECEIVABLE = ("TAX_INVOICE", "BILL_OF_SUPPLY", "DEBIT_NOTE")


@dataclass(frozen=True)
class Imported:
    added: int
    duplicates: int
    skipped_rows: list[int]
    line_count: int


def import_statement(
    principal: Principal, data: bytes, account_label: str, mapping: dict[str, str] | None
) -> Imported:
    require(principal, RECORD)
    s = statement.read(data, mapping)
    if not s.ready:
        raise Invalid(
            "mapping",
            "The date, narration and amount columns were not found: choose them.",
            code="columns_not_found",
        )
    prints = statement.fingerprints(account_label, s.lines)
    known = set(
        BankLine.objects.filter(fingerprint__in=prints).values_list("fingerprint", flat=True)
    )
    new = [
        BankLine(
            tenant_id=principal.tenant_id,  # bulk_create skips save(), which sets it
            account_label=account_label.strip(),
            line_date=line.line_date,
            narration=line.narration,
            reference=line.reference,
            money_in=line.money_in,
            money_out=line.money_out,
            balance=line.balance,
            fingerprint=fp,
            created_by_id=principal.user_id,
        )
        for line, fp in zip(s.lines, prints, strict=True)
        if fp not in known
    ]
    with transaction.atomic():
        BankLine.objects.bulk_create(new)
    return Imported(len(new), len(s.lines) - len(new), s.skipped_rows, len(s.lines))


# --- suggestions ------------------------------------------------------------------------


@dataclass(frozen=True)
class Suggestion:
    kind: str  # payment | vendor_payment | bill | vendor_bill
    id: uuid.UUID
    party_id: uuid.UUID
    party_name: str
    title: str  # in words: "Payment of 25 Oct" / "Tax invoice INV/0002"
    score: int


def _tokens(text: str | None) -> set[str]:
    """Words that can name a transfer: UTRs, cheque numbers, long numbers."""
    return {t for t in re.split(r"[^A-Za-z0-9]+", (text or "").upper()) if len(t) >= 6}


def _names_in(narration: str, name: str) -> bool:
    words = [w for w in re.split(r"[^A-Za-z]+", name.upper()) if len(w) >= 4]
    text = narration.upper()
    return bool(words) and words[0] in text


def _score(line: BankLine, when: Any, reference: str | None, party_name: str) -> int:
    score = 50
    if _tokens(reference) & (_tokens(line.reference) | _tokens(line.narration)):
        score += 30
    if _names_in(line.narration, party_name):
        score += 15
    days = abs((when - line.line_date).days) if when else NEAR_DAYS
    return score + (10 if days == 0 else -days)


def suggestions(line: BankLine, limit: int = 5) -> list[Suggestion]:
    if line.status != "OPEN":
        return []
    near = (line.line_date - timedelta(days=NEAR_DAYS), line.line_date + timedelta(days=NEAR_DAYS))
    out: list[Suggestion] = []
    if line.money_in > 0:
        linked = BankLine.objects.filter(payment_id__isnull=False).values("payment_id")
        for p in (
            Payment.objects.filter(
                status="RECORDED", amount=line.money_in, payment_date__range=near
            )
            .exclude(pk__in=linked)
            .select_related("party")[:20]
        ):
            out.append(
                Suggestion(
                    "payment",
                    p.pk,
                    p.party_id,
                    p.party.display_name,
                    f"Payment recorded on {p.payment_date:%d %b}",
                    _score(line, p.payment_date, p.reference, p.party.display_name) + 20,
                )
            )
        for d in Document.objects.filter(
            status="ISSUED",
            doc_type__in=RECEIVABLE,
            net_receivable=F("amount_settled") + line.money_in,
        ).select_related("party")[:20]:
            out.append(
                Suggestion(
                    "bill",
                    d.pk,
                    d.party_id,
                    d.party.display_name,
                    f"Bill {d.doc_number}",
                    _score(line, d.doc_date, d.doc_number, d.party.display_name) - 10,
                )
            )
    else:
        linked = BankLine.objects.filter(vendor_payment_id__isnull=False).values(
            "vendor_payment_id"
        )
        for vp in (
            VendorPayment.objects.filter(
                status="RECORDED", amount=line.money_out, payment_date__range=near
            )
            .exclude(pk__in=linked)
            .select_related("vendor_party")[:20]
        ):
            out.append(
                Suggestion(
                    "vendor_payment",
                    vp.pk,
                    vp.vendor_party_id,
                    vp.vendor_party.display_name,
                    f"Payment to a vendor recorded on {vp.payment_date:%d %b}",
                    _score(line, vp.payment_date, vp.reference, vp.vendor_party.display_name) + 20,
                )
            )
        for b in VendorBill.objects.filter(
            status="RECORDED", net_payable=F("amount_paid") + line.money_out
        ).select_related("vendor_party")[:20]:
            out.append(
                Suggestion(
                    "vendor_bill",
                    b.pk,
                    b.vendor_party_id,
                    b.vendor_party.display_name,
                    f"Vendor bill {b.bill_number}",
                    _score(line, b.bill_date, b.bill_number, b.vendor_party.display_name) - 10,
                )
            )
    out.sort(key=lambda s: s.score, reverse=True)
    return out[:limit]


# --- what a person decides --------------------------------------------------------------


def _open(line_id: uuid.UUID) -> BankLine:
    line = get_or_404(BankLine, line_id, for_update=True)
    if line.status != "OPEN":
        raise Conflict(
            "This line is already matched or ignored; reopen it first.", code="bank_line_closed"
        )
    return line


def _link(line: BankLine, expected: int, **link: Any) -> None:
    try:
        with transaction.atomic():
            update_versioned(BankLine.objects, line.pk, expected, status="MATCHED", **link)
    except IntegrityError as exc:  # the payment is already another line's money
        raise Invalid(
            "payment_id",
            "This payment is already matched to another bank line.",
            code="already_matched",
        ) from exc


def match(
    principal: Principal,
    line_id: uuid.UUID,
    expected: int,
    payment_id: uuid.UUID | None,
    vendor_payment_id: uuid.UUID | None,
) -> BankLine:
    """This line is that payment (in) or that payment to a vendor (out)."""
    require(principal, RECORD)
    with transaction.atomic():
        line = _open(line_id)
        if line.money_in > 0:
            if payment_id is None:
                raise Invalid("payment_id", "Money in matches a payment received.", code="required")
            p = get_or_invalid(Payment, payment_id, "payment_id", label="payment")
            if p.status != "RECORDED" or p.amount != line.money_in:
                raise Invalid(
                    "payment_id", "The payment's amount is not this line's.", code="amount_mismatch"
                )
            _link(line, expected, payment_id=p.pk)
        else:
            if vendor_payment_id is None:
                raise Invalid(
                    "vendor_payment_id", "Money out matches a payment to a vendor.", code="required"
                )
            vp = get_or_invalid(
                VendorPayment, vendor_payment_id, "vendor_payment_id", label="payment to a vendor"
            )
            if vp.status != "RECORDED" or vp.amount != line.money_out:
                raise Invalid(
                    "vendor_payment_id",
                    "The payment's amount is not this line's.",
                    code="amount_mismatch",
                )
            _link(line, expected, vendor_payment_id=vp.pk)
    return get_or_404(BankLine, line_id)


def _reference(line: BankLine) -> str:
    return (line.reference or line.narration)[:100]


def record(
    principal: Principal, line_id: uuid.UUID, expected: int, data: dict[str, Any]
) -> BankLine:
    """Record the payment this line is (date, amount, reference from the bank),
    set against bills as chosen, and match the line to it: one transaction."""
    require(principal, RECORD)
    with transaction.atomic():
        line = _open(line_id)
        common = {
            "payment_date": line.line_date,
            "mode": "BANK_TRANSFER",
            "reference": _reference(line),
            "project_id": data.get("project_id"),
        }
        if line.money_in > 0:
            if not data.get("party_id"):
                raise Invalid("party_id", "Choose who paid.", code="required")
            p = payments.record_payment(
                principal,
                {
                    **common,
                    "party_id": data["party_id"],
                    "amount": line.money_in,
                    "allocations": data.get("allocations") or [],
                },
            )
            _link(line, expected, payment_id=p.pk)
        else:
            if not data.get("vendor_party_id"):
                raise Invalid("vendor_party_id", "Choose who was paid.", code="required")
            vp = payables.record_payment(
                principal,
                {
                    **common,
                    "vendor_party_id": data["vendor_party_id"],
                    "amount": line.money_out,
                    "allocations": data.get("vendor_allocations") or [],
                },
            )
            _link(line, expected, vendor_payment_id=vp.pk)
    return get_or_404(BankLine, line_id)


def ignore(principal: Principal, line_id: uuid.UUID, expected: int, note: str | None) -> BankLine:
    """Not a payment to match: bank charges, interest, transfers between own accounts."""
    require(principal, RECORD)
    with transaction.atomic():
        line = _open(line_id)
        update_versioned(BankLine.objects, line.pk, expected, status="IGNORED", note=note)
    return get_or_404(BankLine, line_id)


def reopen(principal: Principal, line_id: uuid.UUID, expected: int) -> BankLine:
    """Undo a match or an ignore; a payment recorded from the line stays recorded."""
    require(principal, RECORD)
    with transaction.atomic():
        line = get_or_404(BankLine, line_id, for_update=True)
        if line.status == "OPEN":
            raise Conflict("This line is already open.", code="bank_line_open")
        update_versioned(
            BankLine.objects,
            line.pk,
            expected,
            status="OPEN",
            payment_id=None,
            vendor_payment_id=None,
            note=None,
        )
    return get_or_404(BankLine, line_id)
