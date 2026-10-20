"""Retention releases (Phase 3.3, docs/02-api-design.md §6).

Retention is deducted from what the client pays on each bill; GST was
charged on the full value then. When the client releases it, a release
records the money now due. It is not a tax document: it is settled by
payments through allocations, like an invoice, and shows in receivables.

At most the retention still held can be released, per project and book:
deducted on issued tax invoices (GST) or bills of supply (NON_GST), less
releases not cancelled. Releasing and cancelling a bill both lock the
project row, so they cannot interleave and over-release.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.errors import Conflict, Invalid
from apps.core.permissions import require
from apps.core.queries import get_or_404, get_or_invalid
from apps.core.tenancy import Principal
from apps.core.versioning import update_versioned
from apps.documents.models import Document
from apps.projects.models import Project

from .models import Allocation, RetentionRelease

BOOK_DOC_TYPE = {"GST": "TAX_INVOICE", "NON_GST": "BILL_OF_SUPPLY"}
ZERO = Decimal("0.00")


@dataclass(frozen=True)
class Position:
    deducted: Decimal
    released: Decimal

    @property
    def available(self) -> Decimal:
        return self.deducted - self.released


def position(project_id: uuid.UUID) -> dict[str, Position]:
    """Retention deducted and released per book, as of now."""
    deducted = dict(
        Document.objects.filter(
            project_id=project_id, status="ISSUED", doc_type__in=BOOK_DOC_TYPE.values()
        )
        .values("doc_type")
        .annotate(t=Sum("retention_amount"))
        .values_list("doc_type", "t")
    )
    released = dict(
        RetentionRelease.objects.filter(project_id=project_id, status="RELEASED")
        .values("book")
        .annotate(t=Sum("amount"))
        .values_list("book", "t")
    )
    return {
        book: Position(deducted.get(doc_type) or ZERO, released.get(book) or ZERO)
        for book, doc_type in BOOK_DOC_TYPE.items()
    }


def _lock_project(project_id: uuid.UUID) -> None:
    list(Project.objects.select_for_update().filter(pk=project_id))


def project_retention(principal: Principal, project_id: uuid.UUID) -> dict[str, Position]:
    require(principal, "tenant.read")
    get_or_404(Project, project_id)
    return position(project_id)


def get_release(principal: Principal, release_id: uuid.UUID) -> RetentionRelease:
    require(principal, "tenant.read")
    return get_or_404(RetentionRelease, release_id)


def release_allocations(release: RetentionRelease) -> list[Allocation]:
    return list(Allocation.objects.filter(retention_release_id=release.pk).order_by("created_at"))


def release(principal: Principal, data: dict[str, Any]) -> RetentionRelease:
    require(principal, "documents.issue")
    project = get_or_invalid(Project, data["project_id"], "project_id", label="project")
    with transaction.atomic():
        _lock_project(project.pk)
        held = position(project.pk)
        book = data.get("book") or ("GST" if held["GST"].available > 0 else "NON_GST")
        available = held[book].available
        if available <= 0:
            raise Invalid(
                "amount", "No retention is held on this project.", code="nothing_to_release"
            )
        if data["amount"] > available:
            raise Invalid(
                "amount",
                f"At most {available} of retention is held ({book} bills).",
                code="exceeds_retention_held",
            )
        row = RetentionRelease(
            project_id=project.pk,
            party_id=project.client_party_id,
            book=book,
            release_date=data["release_date"],
            due_date=data.get("due_date"),
            amount=data["amount"],
            reference=data.get("reference"),
            notes=data.get("notes"),
            created_by_id=principal.user_id,
        )
        row.save()
    return get_or_404(RetentionRelease, row.pk)


def cancel_release(
    principal: Principal, release_id: uuid.UUID, expected: int, reason: str
) -> RetentionRelease:
    require(principal, "documents.issue")
    with transaction.atomic():
        row = get_or_404(RetentionRelease, release_id, for_update=True)
        if row.status == "CANCELLED":
            raise Conflict("This release is already cancelled.", code="release_cancelled")
        if row.amount_settled:
            raise Conflict(
                "Payments are allocated to this release; unwind them first.",
                code="release_settled",
            )
        update_versioned(
            RetentionRelease.objects,
            row.pk,
            expected,
            status="CANCELLED",
            cancelled_at=timezone.now(),
            cancelled_by_id=principal.user_id,
            cancel_reason=reason,
        )
    return get_or_404(RetentionRelease, release_id)


def check_bill_cancellable(doc: Document) -> None:
    """Cancelling a bill takes its retention out of what was deducted: refuse
    when releases already rely on it. Call inside the cancel transaction."""
    book = next((b for b, t in BOOK_DOC_TYPE.items() if t == doc.doc_type), None)
    if not doc.project_id or not doc.retention_amount or book is None:
        return
    _lock_project(doc.project_id)
    if position(doc.project_id)[book].available < doc.retention_amount:
        raise Conflict(
            "Retention from this bill has been released; cancel the retention release first.",
            code="retention_released",
        )
