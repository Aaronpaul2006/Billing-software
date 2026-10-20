"""Payments received and their allocation to documents (docs/02-api-design.md §6).

The database owns the money rules: the allocations trigger locks the
document and the payment, keeps documents.amount_settled in step, and
rejects over-allocation, so concurrent requests cannot double-settle an
invoice or spend a payment twice. This service checks the same rules first
to give clear, per-field errors; database rejections that can only happen
in a race are mapped to the same codes.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.core.errors import Conflict, Invalid
from apps.core.permissions import require
from apps.core.queries import get_or_404, get_or_invalid
from apps.core.tenancy import Principal
from apps.core.versioning import update_versioned
from apps.documents.models import Document
from apps.parties.models import Party
from apps.projects.models import Project

from .models import Allocation, Payment

SETTLEABLE = frozenset({"TAX_INVOICE", "BILL_OF_SUPPLY", "DEBIT_NOTE"})
ZERO = Decimal("0.00")


@dataclass(frozen=True)
class Source:
    """Where settlement money comes from: a payment or an issued credit note."""

    payment_id: uuid.UUID | None
    credit_note_id: uuid.UUID | None
    party_id: uuid.UUID
    total: Decimal
    label: str  # "payment" / "credit note", for messages
    exceeds_code: str


def payment_source(payment: Payment) -> Source:
    return Source(
        payment.pk, None, payment.party_id, payment.amount, "payment", "allocation_exceeds_payment"
    )


def credit_note_source(note: Document) -> Source:
    return Source(
        None, note.pk, note.party_id, note.grand_total, "credit note", "allocation_exceeds_credit"
    )


def allocated_from(source: Source) -> Decimal:
    rows = (
        Allocation.objects.filter(payment_id=source.payment_id)
        if source.payment_id
        else Allocation.objects.filter(credit_note_id=source.credit_note_id)
    )
    return rows.aggregate(t=Sum("amount"))["t"] or ZERO


def allocated_total(payment_id: uuid.UUID) -> Decimal:
    total = Allocation.objects.filter(payment_id=payment_id).aggregate(t=Sum("amount"))["t"]
    return total or ZERO


def get_payment(principal: Principal, payment_id: uuid.UUID) -> Payment:
    require(principal, "tenant.read")
    return get_or_404(Payment, payment_id)


def _db_error_to_problem(exc: DatabaseError, field: str, source: Source | None = None) -> Exception:
    """Rules the database enforced (a race the pre-checks could not see)."""
    text = str(exc)
    label = source.label if source else "payment"
    if isinstance(exc, IntegrityError) and (
        "allocations_payment_uq" in text or "allocations_cn_uq" in text
    ):
        return Conflict(
            f"This {label} is already allocated to that document.", code="already_allocated"
        )
    if "documents_amount_settled_check" in text:
        return Invalid(
            field,
            "More than the document's outstanding amount.",
            code="allocation_exceeds_outstanding",
        )
    if "exceeds the unallocated amount" in text:
        return Invalid(
            field,
            f"More than the {label}'s unallocated amount.",
            code=source.exceeds_code if source else "allocation_exceeds_payment",
        )
    if "can be settled" in text:
        return Invalid(
            field,
            "Only issued invoices, bills of supply and debit notes are settled.",
            code="document_not_settleable",
        )
    if "same party" in text:
        return Invalid(field, "The document belongs to another party.", code="party_mismatch")
    return exc


def _allocate(principal: Principal, source: Source, items: list[dict[str, Any]]) -> None:
    """Allocate `items` from a source whose row the caller has locked."""
    seen: set[uuid.UUID] = set()
    available = source.total - allocated_from(source)
    for i, item in enumerate(items):
        field = f"allocations[{i}]"
        doc = get_or_invalid(
            Document, item["document_id"], f"{field}.document_id", label="document"
        )
        if doc.pk in seen:
            raise Invalid(f"{field}.document_id", "Listed twice.", code="duplicate")
        seen.add(doc.pk)
        if doc.status != "ISSUED" or doc.doc_type not in SETTLEABLE:
            raise Invalid(
                f"{field}.document_id",
                "Only issued invoices, bills of supply and debit notes are settled.",
                code="document_not_settleable",
            )
        if doc.party_id != source.party_id:
            raise Invalid(
                f"{field}.document_id",
                "The document belongs to another party.",
                code="party_mismatch",
            )
        amount: Decimal = item["amount"]
        outstanding = doc.net_receivable - doc.amount_settled
        if amount > outstanding:
            raise Invalid(
                f"{field}.amount",
                f"More than the outstanding {outstanding}.",
                code="allocation_exceeds_outstanding",
            )
        if amount > available:
            raise Invalid(
                f"{field}.amount",
                f"More than the {source.label}'s unallocated {available}.",
                code=source.exceeds_code,
            )
        available -= amount
        try:
            with transaction.atomic():
                Allocation(
                    document_id=doc.pk,
                    payment_id=source.payment_id,
                    credit_note_id=source.credit_note_id,
                    amount=amount,
                    created_by_id=principal.user_id,
                ).save()
        except DatabaseError as exc:
            raise _db_error_to_problem(exc, f"{field}.amount", source) from exc


def _allocate_payment(principal: Principal, payment: Payment, items: list[dict[str, Any]]) -> None:
    if payment.status != "RECORDED":
        raise Conflict("This payment is voided.", code="payment_voided")
    _allocate(principal, payment_source(payment), items)


def record_payment(principal: Principal, data: dict[str, Any]) -> Payment:
    require(principal, "payments.record")
    party = get_or_invalid(Party, data["party_id"], "party_id", label="party")
    if not party.is_customer:
        raise Invalid("party_id", "This party is not a customer.", code="not_a_customer")
    if data.get("project_id"):
        project = get_or_invalid(Project, data["project_id"], "project_id", label="project")
        if project.client_party_id != party.pk:
            raise Invalid(
                "project_id", "This project belongs to another client.", code="party_mismatch"
            )
    allocations = data.pop("allocations", None) or []
    with transaction.atomic():
        payment = Payment(**data, created_by_id=principal.user_id)
        payment.save()
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        _allocate_payment(principal, payment, allocations)
    return get_or_404(Payment, payment.pk)


def allocate(principal: Principal, payment_id: uuid.UUID, items: list[dict[str, Any]]) -> Payment:
    require(principal, "payments.record")
    with transaction.atomic():
        payment = get_or_404(Payment, payment_id, for_update=True)
        _allocate_payment(principal, payment, items)
    return get_or_404(Payment, payment_id)


def unwind(principal: Principal, allocation_id: uuid.UUID) -> None:
    """Delete an allocation; the trigger lowers the document's amount_settled."""
    require(principal, "payments.record")
    with transaction.atomic():
        allocation = get_or_404(Allocation, allocation_id, for_update=True)
        allocation.delete()


def void_payment(
    principal: Principal, payment_id: uuid.UUID, expected: int, reason: str
) -> Payment:
    """Void (never delete) a payment; its allocations are unwound first. Audited."""
    require(principal, "payments.record")
    with transaction.atomic():
        payment = get_or_404(Payment, payment_id, for_update=True)
        if payment.status == "VOIDED":
            raise Conflict("This payment is already voided.", code="payment_voided")
        Allocation.objects.filter(payment_id=payment.pk).delete()
        update_versioned(
            Payment.objects,
            payment.pk,
            expected,
            status="VOIDED",
            voided_at=timezone.now(),
            voided_by_id=principal.user_id,
            void_reason=reason,
        )
    return get_or_404(Payment, payment_id)


# --- credit notes ----------------------------------------------------------------------


def apply_credit_note(
    principal: Principal, note_id: uuid.UUID, items: list[dict[str, Any]]
) -> Document:
    """Settle invoices / debit notes of the same party with an issued credit note."""
    require(principal, "payments.record")
    with transaction.atomic():
        note = get_or_404(Document, note_id, for_update=True)
        if note.doc_type != "CREDIT_NOTE" or note.status != "ISSUED":
            raise Conflict(
                "Only an issued credit note can be applied.", code="not_an_issued_credit_note"
            )
        _allocate(principal, credit_note_source(note), items)
    return get_or_404(Document, note_id)


def document_allocations(
    principal: Principal, doc_id: uuid.UUID
) -> tuple[Document, list[Allocation]]:
    """Allocations settling a document, or (for a credit note) made from it."""
    require(principal, "tenant.read")
    doc = get_or_404(Document, doc_id)
    rows = Allocation.objects.filter(Q(document_id=doc.pk) | Q(credit_note_id=doc.pk))
    return doc, list(rows.order_by("created_at"))
