"""Notifications (Part B): few, each worth a look, each sent once.

- A client accepts or declines a quotation in the portal: those who issue bills.
- Daily, bills that became overdue yesterday: those who record payments.
- Daily, vendor bills and released subcontractor retention due within 3 days
  and not yet paid: those who record payments.
- Someone joins from an invitation: those who manage members.

A notification goes to each active member with one of the roles; dedupe_key
keeps it to one per event per person (the daily job may run twice).
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import F, Q, Sum

from apps.accounts.models import Membership
from apps.core.tenancy import tenant_context
from apps.documents.models import Document
from apps.documents.pdf.render import inr
from apps.payables.models import VendorBill, VendorRetentionRelease

from .models import Kind, Notification


def format_inr(amount: Decimal) -> str:
    return f"₹{inr(amount)}"


ISSUERS = ("OWNER", "ADMIN", "ACCOUNTANT")  # documents.issue, payments.record
MANAGERS = ("OWNER", "ADMIN")  # members.manage
RECEIVABLE = ("TAX_INVOICE", "BILL_OF_SUPPLY", "DEBIT_NOTE")
DUE_SOON = timedelta(days=3)


def send(
    tenant_id: uuid.UUID,
    roles: tuple[str, ...],
    *,
    kind: str,
    title: str,
    dedupe_key: str,
    body: str | None = None,
    link: str | None = None,
    skip_user: uuid.UUID | None = None,
) -> int:
    """To each active member with one of the roles (in the tenant's context)."""
    members = Membership.objects.filter(status="ACTIVE", role__in=roles)
    if skip_user is not None:
        members = members.exclude(user_id=skip_user)
    users = members.values_list("user_id", flat=True)
    rows = [
        Notification(
            tenant_id=tenant_id,  # bulk_create skips save(): set it here
            user_id=user_id,
            kind=kind,
            title=title[:200],
            body=body[:1000] if body else None,
            link=link,
            dedupe_key=dedupe_key,
        )
        for user_id in set(users)
    ]
    Notification.objects.bulk_create(rows, ignore_conflicts=True)
    return len(rows)


def quotation_response(tenant_id: uuid.UUID, doc_id: uuid.UUID, accepted: bool) -> int:
    """A client's answer to a quotation, from the portal (after it is saved)."""
    with tenant_context(tenant_id):
        doc = Document.objects.select_related("party").get(pk=doc_id)
        word = "accepted" if accepted else "declined"
        return send(
            tenant_id,
            ISSUERS,
            kind=Kind.QUOTATION_ACCEPTED if accepted else Kind.QUOTATION_DECLINED,
            title=f"{doc.party.display_name} {word} {doc.doc_number}",
            body=f"Quotation for {format_inr(doc.grand_total)}"
            + (". Make the bill from it when the work starts." if accepted else "."),
            link=f"/documents/{doc.pk}",
            dedupe_key=f"quotation:{doc.pk}:{word}",
        )


def member_joined(tenant_id: uuid.UUID, user_id: uuid.UUID, name: str, role: str) -> int:
    """Someone joined from an invitation (in the tenant's context already)."""
    return send(
        tenant_id,
        MANAGERS,
        kind=Kind.MEMBER_JOINED,
        title=f"{name} joined as {role.replace('_', ' ').lower()}",
        link="/settings/members",
        dedupe_key=f"member:{user_id}",
        skip_user=user_id,
    )


def daily(tenant_id: uuid.UUID, today: date) -> int:
    """Bills overdue since yesterday, and payables due within 3 days."""
    sent = 0
    with tenant_context(tenant_id):
        yesterday = today - timedelta(days=1)
        overdue = Document.objects.filter(
            status="ISSUED", doc_type__in=RECEIVABLE, amount_settled__lt=F("net_receivable")
        ).filter(Q(due_date=yesterday) | Q(due_date__isnull=True, doc_date=yesterday))
        late = overdue.aggregate(n=Sum(F("net_receivable") - F("amount_settled")))["n"]
        count = overdue.count()
        if count:
            sent += send(
                tenant_id,
                ISSUERS,
                kind=Kind.BILLS_OVERDUE,
                title=f"{count} {'bill' if count == 1 else 'bills'} overdue since yesterday",
                body=f"{format_inr(late or Decimal(0))} still to collect. Send a reminder from "
                "the dashboard.",
                link="/",
                dedupe_key=f"overdue:{today.isoformat()}",
            )

        until = today + DUE_SOON
        bills = VendorBill.objects.filter(
            status="RECORDED", amount_paid__lt=F("net_payable")
        ).filter(
            Q(due_date__range=(today, until))
            | Q(due_date__isnull=True, bill_date__range=(today, until))
        )
        releases = VendorRetentionRelease.objects.filter(
            status="RELEASED", amount_paid__lt=F("amount")
        ).filter(
            Q(due_date__range=(today, until))
            | Q(due_date__isnull=True, release_date__range=(today, until))
        )
        owed = (bills.aggregate(n=Sum(F("net_payable") - F("amount_paid")))["n"] or 0) + (
            releases.aggregate(n=Sum(F("amount") - F("amount_paid")))["n"] or 0
        )
        count = bills.count() + releases.count()
        if count:
            sent += send(
                tenant_id,
                ISSUERS,
                kind=Kind.PAYABLES_DUE,
                title=f"{count} {'payment' if count == 1 else 'payments'} to vendors due by "
                f"{until:%d %b}",
                body=f"{format_inr(Decimal(owed))} to pay.",
                link="/vendor-bills",
                dedupe_key=f"payables:{today.isoformat()}",
            )
    return sent
