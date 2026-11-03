"""Issue, cancel, accept / decline, convert, credit & debit notes
(docs/01-architecture.md §5.2-§5.3, docs/02-api-design.md §5).

Issuing assigns the number under a row lock on the series, inside the same
transaction as everything else: concurrent issuers serialize on the lock,
and a failure rolls the counter back too, so numbering stays gapless. The
database trigger re-verifies totals, lines and supply type at issue.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.services import require_verified_email
from apps.core.errors import Conflict, Invalid, PreconditionFailed
from apps.core.india import fy_start_year
from apps.core.permissions import require
from apps.core.queries import get_or_404
from apps.core.tenancy import Principal
from apps.core.versioning import update_versioned
from apps.parties.models import Party
from apps.payments import retention
from apps.payments.models import Allocation
from apps.tenants.models import DocumentSeries, GstRegistration, Tenant

from ..models import Document, DocumentLine
from . import drafts, ra_bills
from .pdfs import enqueue_pdf

CONVERSIONS: dict[str, frozenset[str]] = {
    "QUOTATION": frozenset({"PROFORMA", "TAX_INVOICE", "BILL_OF_SUPPLY"}),
    "PROFORMA": frozenset({"TAX_INVOICE", "BILL_OF_SUPPLY"}),
}
CONVERTIBLE_STATUSES = frozenset({"ISSUED", "ACCEPTED"})


def _locked(doc_id: uuid.UUID, expected: int | None) -> Document:
    doc = get_or_404(Document, doc_id, for_update=True)
    if expected is not None and doc.version != expected:
        raise PreconditionFailed()  # the view attaches the current document
    return doc


def _supplier_snapshot(registration: GstRegistration, *, lut: bool) -> dict[str, Any]:
    tenant = Tenant.objects.get(pk=registration.tenant_id)
    return {
        # the LUT the document was issued under (printed on SEZ / export invoices)
        "lut_arn": registration.lut_arn if lut else None,
        "gstin": registration.gstin,
        "registration_type": registration.registration_type,
        "legal_name": registration.legal_name,
        "trade_name": registration.trade_name,
        "state_code": registration.state_code,
        "address": registration.address,
        "pan": tenant.pan,
    }


def _party_snapshot(party: Party) -> dict[str, Any]:
    return {
        "display_name": party.display_name,
        "legal_name": party.legal_name,
        "gst_treatment": party.gst_treatment,
        "gstin": party.gstin,
        "pan": party.pan,
        "state_code": party.state_code,
        "billing_address": party.billing_address,
        "email": party.email,
        "phone": party.phone,
    }


def _check_note_limits(doc: Document, grand_total: Decimal) -> None:
    original = Document.objects.select_for_update().filter(pk=doc.original_document_id).first()
    if original is None or original.status != "ISSUED":
        raise Conflict("The original invoice is no longer issued.", code="original_not_issued")
    if doc.doc_type == "CREDIT_NOTE":
        credited = (
            Document.objects.filter(
                original_document_id=original.pk, doc_type="CREDIT_NOTE", status="ISSUED"
            ).aggregate(total=Sum("grand_total"))["total"]
        ) or Decimal("0.00")
        if credited + grand_total > original.grand_total:
            raise Invalid(
                "lines",
                f"Credit notes would exceed the invoice total ({original.grand_total}).",
                code="credit_exceeds_original",
            )


def issue(principal: Principal, doc_id: uuid.UUID, expected: int) -> Document:
    require(principal, "documents.issue")
    require_verified_email(principal.user_id)
    with transaction.atomic():
        doc = _locked(doc_id, expected)
        if doc.status != "DRAFT":
            raise Conflict("Only drafts can be issued.", code="document_not_draft")

        # Recompute at the moment of issue: project settings, the advance
        # still outstanding and BOQ quantities billed may have changed since
        # the draft was saved. The BOQ rows are locked first, so bills issued
        # concurrently cannot together pass a contract quantity.
        state = drafts.current_state(doc)
        ra_bills.lock_boq_items(state["lines"])
        computed = drafts._compute(state, doc_id=doc.pk)
        if not computed.lines:
            raise Invalid("lines", "Add at least one line before issuing.", code="no_lines")
        if doc.original_document_id:
            _check_note_limits(doc, computed.out.grand_total)

        series = (
            DocumentSeries.objects.select_for_update()
            .filter(
                gst_registration_id=computed.resolved.registration.pk,
                doc_type=doc.doc_type,
                fy_start_year=fy_start_year(doc.doc_date),
                is_active=True,
            )
            .first()
        )
        if series is None:
            raise Conflict(
                f"No active {doc.doc_type} number series for this registration and the"
                f" financial year {fy_start_year(doc.doc_date)}.",
                code="series_missing",
            )
        number = f"{series.prefix}{series.next_number:0{series.pad_width}d}"
        DocumentSeries.objects.filter(pk=series.pk).update(
            next_number=series.next_number + 1, updated_at=timezone.now()
        )

        header = drafts._header(computed, drafts.current_state(doc))
        DocumentLine.objects.filter(document_id=doc.pk).delete()
        drafts._write_lines(doc, computed)
        update_versioned(
            Document.objects,
            doc.pk,
            expected,
            **header,
            status="ISSUED",
            series_id=series.pk,
            doc_number=number,
            supplier_snapshot=_supplier_snapshot(computed.resolved.registration, lut=computed.lut),
            party_snapshot=_party_snapshot(computed.resolved.party),
            issued_at=timezone.now(),
            issued_by_id=principal.user_id,
        )
        if settings.RENDER_PDF_ON_ISSUE:
            enqueue_pdf(principal.tenant_id, principal.user_id, doc.pk)
    return get_or_404(Document, doc_id)


def cancel(principal: Principal, doc_id: uuid.UUID, expected: int, reason: str) -> Document:
    require(principal, "documents.issue")
    with transaction.atomic():
        doc = _locked(doc_id, expected)
        if doc.status != "ISSUED":
            raise Conflict(f"A {doc.status} document cannot be cancelled.", code="not_cancellable")
        if doc.amount_settled:
            raise Conflict(
                "Payments are allocated to this document; unwind them first.",
                code="document_settled",
            )
        if Document.objects.filter(original_document_id=doc.pk, status="ISSUED").exists():
            raise Conflict(
                "Issued credit or debit notes refer to this document; cancel them first.",
                code="has_issued_notes",
            )
        if Allocation.objects.filter(credit_note_id=doc.pk).exists():
            raise Conflict(
                "This credit note is allocated to invoices; unwind that first.",
                code="credit_note_allocated",
            )
        retention.check_bill_cancellable(doc)
        update_versioned(
            Document.objects,
            doc.pk,
            expected,
            status="CANCELLED",
            cancelled_at=timezone.now(),
            cancelled_by_id=principal.user_id,
            cancel_reason=reason,
            # The stored PDF shows it issued: render again with CANCELLED across
            # it. The old file stays in storage as a record of what was sent.
            pdf_attachment_id=None,
        )
        if settings.RENDER_PDF_ON_ISSUE:
            enqueue_pdf(principal.tenant_id, principal.user_id, doc.pk)
    return get_or_404(Document, doc_id)


def respond_to_quotation(
    principal: Principal, doc_id: uuid.UUID, expected: int, *, accept: bool
) -> Document:
    require(principal, "documents.issue")
    record_quotation_response(doc_id, expected, accept=accept)
    return get_or_404(Document, doc_id)


def record_quotation_response(doc_id: uuid.UUID, expected: int, *, accept: bool) -> None:
    """ISSUED quotation → ACCEPTED / DECLINED. Callers check who may answer:
    staff with documents.issue, or the client in the portal (apps.portal)."""
    with transaction.atomic():
        doc = _locked(doc_id, expected)
        if doc.doc_type != "QUOTATION":
            raise Conflict("Only quotations are accepted or declined.", code="not_a_quotation")
        if doc.status != "ISSUED":
            raise Conflict(f"This quotation is {doc.status}.", code="not_issued")
        update_versioned(
            Document.objects, doc.pk, expected, status="ACCEPTED" if accept else "DECLINED"
        )


DUPLICABLE = frozenset({"QUOTATION", "PROFORMA", "TAX_INVOICE", "BILL_OF_SUPPLY"})


def duplicate(principal: Principal, doc_id: uuid.UUID, doc_date: date) -> Document:
    """A new draft copied from any bill or quotation (B.10), dated `doc_date`:
    same type, client, project, lines and measurements; the due date comes
    from the client's terms again; a quotation keeps its validity length."""
    require(principal, "documents.draft")
    source = get_or_404(Document, doc_id)
    if source.doc_type not in DUPLICABLE:
        raise Conflict(
            "A credit or debit note belongs to its bill: make a new one from the bill.",
            code="not_duplicable",
        )
    valid_until = None
    if source.doc_type == "QUOTATION" and source.valid_until:
        valid_until = doc_date + (source.valid_until - source.doc_date)
    data = {
        **drafts.current_state(source),
        "doc_date": doc_date,
        "due_date": None,
        "valid_until": valid_until,
    }
    return drafts._create(principal, data)


def convert(principal: Principal, doc_id: uuid.UUID, to: str, doc_date: date) -> Document:
    """A new draft copied from an issued / accepted quotation or proforma."""
    require(principal, "documents.draft")
    source = get_or_404(Document, doc_id)
    allowed = CONVERSIONS.get(source.doc_type, frozenset())
    if to not in allowed:
        raise Invalid("to", f"A {source.doc_type} cannot become a {to}.", code="not_convertible")
    if source.status not in CONVERTIBLE_STATUSES:
        raise Conflict(
            f"A {source.status} {source.doc_type} cannot be converted.", code="not_convertible"
        )
    data = {
        **drafts.current_state(source),
        "doc_type": to,
        "doc_date": doc_date,
        "due_date": None,
        "valid_until": None,
    }
    return drafts._create(principal, data, source_document_id=source.pk)


def create_note(
    principal: Principal,
    original_id: uuid.UUID,
    note_type: str,
    doc_date: date,
    lines: list[dict[str, Any]] | None,
    notes: str | None,
) -> Document:
    """A draft credit / debit note against an issued tax invoice. Without
    `lines` the invoice's lines are copied, to be edited down to the change."""
    require(principal, "documents.draft")
    original = get_or_404(Document, original_id)
    if original.doc_type != "TAX_INVOICE" or original.status != "ISSUED":
        raise Conflict(
            "Credit and debit notes adjust an issued tax invoice.", code="not_an_issued_invoice"
        )
    if doc_date < original.doc_date:
        raise Invalid("doc_date", "A note cannot predate its invoice.", code="invalid_dates")
    data = {
        **drafts.current_state(original),
        "doc_type": note_type,
        "doc_date": doc_date,
        "due_date": None,
        "valid_until": None,
        "notes": notes,
        "is_ra_bill": False,  # a note adjusts an RA bill; it is not one
        "lines": lines if lines is not None else drafts.current_state(original)["lines"],
    }
    return drafts._create(principal, data, original_document_id=original.pk)
