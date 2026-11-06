"""Bill approval (Part B).

A business may set an approval limit (tenants.approval_limit). A bill or note
at or above it, issued by anyone but an owner, needs an owner's approval of
exactly the version being issued: an edit after the approval bumps the
version, so the approval no longer holds. Owners need none (issuing is their
approval). Asking for approval tells the owners (the bell); an approval tells
whoever asked.
"""

import uuid
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.errors import Conflict, Forbidden, PreconditionFailed
from apps.core.permissions import require
from apps.core.queries import get_or_404
from apps.core.tenancy import Principal
from apps.documents.pdf.render import inr
from apps.tenants.models import Tenant

from ..models import Document

APPROVER = "OWNER"
TYPES = frozenset({"TAX_INVOICE", "BILL_OF_SUPPLY", "DEBIT_NOTE", "CREDIT_NOTE"})
TITLES = {
    "TAX_INVOICE": "tax invoice",
    "BILL_OF_SUPPLY": "bill of supply",
    "DEBIT_NOTE": "debit note",
    "CREDIT_NOTE": "credit note",
}


def limit(tenant_id: uuid.UUID) -> Decimal | None:
    value: Decimal | None = Tenant.objects.get(pk=tenant_id).approval_limit
    return value


def needed(principal: Principal, doc: Document, grand_total: Decimal) -> bool:
    """Does this person need an owner's approval to issue it?"""
    if principal.role == APPROVER or doc.doc_type not in TYPES:
        return False
    cap = limit(principal.tenant_id)
    return cap is not None and grand_total >= cap


def holds(doc: Document) -> bool:
    """An approval of the version as it is now."""
    return doc.approved_version is not None and doc.approved_version == doc.version


def check(principal: Principal, doc: Document, grand_total: Decimal) -> None:
    """Called when issuing: refuse a bill that needs an approval it lacks."""
    if needed(principal, doc, grand_total) and not holds(doc):
        raise Conflict(
            f"Bills of ₹{inr(limit(principal.tenant_id))} or more need an owner's approval "
            "before they are issued. Ask for approval.",
            code="approval_required",
        )


def _draft(doc_id: uuid.UUID, expected: int) -> Document:
    doc = get_or_404(Document, doc_id, for_update=True)
    if doc.version != expected:
        raise PreconditionFailed()
    if doc.status != "DRAFT":
        raise Conflict("Only drafts are approved.", code="document_not_draft")
    return doc


def ask(principal: Principal, doc_id: uuid.UUID, expected: int) -> Document:
    """Ask the owners to approve this draft (the bell tells them)."""
    from apps.notifications.services import send  # notifications build on documents

    require(principal, "documents.draft")
    with transaction.atomic():
        doc = _draft(doc_id, expected)
        Document.objects.filter(pk=doc.pk).update(
            approval_requested_at=timezone.now(), approval_requested_by_id=principal.user_id
        )
        what = TITLES.get(doc.doc_type, "bill")
        party = doc.party.display_name if doc.party_id else ""
        send(
            principal.tenant_id,
            (APPROVER,),
            kind="APPROVAL_REQUESTED",
            title=f"Please approve a {what} for {party}"[:200],
            body=f"₹{inr(doc.grand_total)}, waiting to be issued.",
            link=f"/documents/{doc.pk}",
            dedupe_key=f"approve:{doc.pk}:{doc.version}",
            skip_user=principal.user_id,
        )
    return get_or_404(Document, doc_id)


def approve(principal: Principal, doc_id: uuid.UUID, expected: int) -> Document:
    """An owner approves the draft as it is now (no new version)."""
    from apps.notifications.models import Notification

    if principal.role != APPROVER:
        raise Forbidden("Only an owner approves bills.", code="approver_only")
    with transaction.atomic():
        doc = _draft(doc_id, expected)
        Document.objects.filter(pk=doc.pk, version=expected).update(
            approved_version=expected, approved_at=timezone.now(), approved_by_id=principal.user_id
        )
        asker = doc.approval_requested_by_id
        if asker and asker != principal.user_id:
            what = TITLES.get(doc.doc_type, "bill")
            Notification.objects.bulk_create(
                [
                    Notification(
                        tenant_id=principal.tenant_id,
                        user_id=asker,
                        kind="BILL_APPROVED",
                        title=f"Your {what} for {doc.party.display_name} is approved"[:200],
                        body="You can issue it now.",
                        link=f"/documents/{doc.pk}",
                        dedupe_key=f"approved:{doc.pk}:{expected}",
                    )
                ],
                ignore_conflicts=True,
            )
    return get_or_404(Document, doc_id)
