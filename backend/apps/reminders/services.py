"""Payment reminders (W.2): emails to a client about an unpaid bill.

Automatic stages are counted from the bill's due date: 3 days before, on the
day, then 7, 15 and 30 days after. The daily job sends only the latest stage
that is due and not yet sent, so a missed day never causes a burst of old
reminders, and the database lets each stage go out at most once per bill.
Bills without a due date, paid bills, clients without an email and clients
switched off (`parties.reminders_enabled`) get nothing automatically.

A member may also send one from the bill ("MANUAL"): at most once a day per
bill, whatever the client's switch, since it is a deliberate act.
"""

import logging
import uuid
import zoneinfo
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.core.mail import send_mail
from django.db import IntegrityError, connection, transaction
from django.db.models import DecimalField, ExpressionWrapper, F
from django.template.loader import render_to_string
from django.utils import timezone

from apps.core.errors import Conflict, DomainError, Invalid
from apps.core.permissions import require
from apps.core.queries import get_or_404
from apps.core.tenancy import Principal, tenant_context
from apps.documents.models import Document
from apps.documents.pdf.render import TITLES, inr
from apps.parties.models import Party
from apps.tenants.models import GstRegistration, Tenant

from .models import PaymentReminder, ReminderStage

log = logging.getLogger(__name__)

SEND = "payments.record"  # chasing payment is part of collections: owner, admin, accountant
RECEIVABLE_TYPES = ("TAX_INVOICE", "BILL_OF_SUPPLY", "DEBIT_NOTE")
# (stage, days after the due date it starts), in order
SCHEDULE: list[tuple[str, int]] = [
    (ReminderStage.BEFORE_DUE, -3),
    (ReminderStage.ON_DUE, 0),
    (ReminderStage.OVERDUE_7, 7),
    (ReminderStage.OVERDUE_15, 15),
    (ReminderStage.OVERDUE_30, 30),
]
RANK = {stage: i for i, (stage, _) in enumerate(SCHEDULE)}
MANUAL_GAP = timedelta(hours=24)


class EmailUnavailable(DomainError):
    status = 503
    code = "email_unavailable"
    detail = "The email could not be sent just now. Try again in a few minutes."


def stage_for(due: date, today: date) -> str | None:
    """The latest stage due on `today` for a bill due on `due` (None before the first)."""
    days = (today - due).days
    current = None
    for stage, starts in SCHEDULE:
        if days >= starts:
            current = stage
    return current


def _outstanding() -> Any:
    return ExpressionWrapper(
        F("net_receivable") - F("amount_settled"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )


def _company(tenant_id: uuid.UUID) -> dict[str, Any]:
    """Who the reminder is from (inside the tenant's context)."""
    tenant = Tenant.objects.get(pk=tenant_id)
    registration = GstRegistration.objects.filter(is_default=True).first()
    return {
        "name": tenant.trade_name or tenant.legal_name,
        "legal_name": tenant.legal_name,
        "gstin": registration.gstin if registration else None,
    }


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    body: str


def build_email(
    doc: Document, party: Party, outstanding: Decimal, stage: str, today: date
) -> Email:
    company = _company(doc.tenant_id)
    title = TITLES[doc.doc_type]
    days_late = (today - doc.due_date).days if doc.due_date else 0
    overdue = days_late > 0
    subject = (
        f"Overdue: {title} {doc.doc_number} from {company['name']}"
        if overdue
        else f"Payment reminder: {title} {doc.doc_number} from {company['name']}"
    )
    body = render_to_string(
        "reminders/email/payment_reminder.txt",
        {
            "client": party.display_name,
            "company": company,
            "title": title,
            "number": doc.doc_number,
            "doc_date": doc.doc_date.strftime("%d %b %Y"),
            "due_date": doc.due_date.strftime("%d %b %Y") if doc.due_date else None,
            "total": inr(doc.net_receivable),
            "outstanding": inr(outstanding),
            "overdue": overdue,
            "days_late": days_late,
            "due_today": doc.due_date == today,
            "manual": stage == ReminderStage.MANUAL,
        },
    )
    return Email(to=str(party.email), subject=subject, body=body)


def _send(email: Email) -> None:
    send_mail(email.subject, email.body, None, [email.to])


# --- the daily job ------------------------------------------------------------------


def active_tenants() -> list[tuple[uuid.UUID, str]]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT tenant_id, time_zone FROM active_tenants()")
        return [(uuid.UUID(str(t)), str(tz)) for t, tz in cursor.fetchall()]


def tenant_today(time_zone: str) -> date:
    try:
        zone = zoneinfo.ZoneInfo(time_zone)
    except zoneinfo.ZoneInfoNotFoundError, ValueError:
        zone = zoneinfo.ZoneInfo("Asia/Kolkata")
    return datetime.now(zone).date()


def send_due_for_tenant(tenant_id: uuid.UUID, today: date) -> int:
    """Send this tenant's due reminders for `today`; returns how many went out."""
    sent = 0
    with tenant_context(tenant_id):
        bills = list(
            Document.objects.filter(
                status="ISSUED",
                doc_type__in=RECEIVABLE_TYPES,
                due_date__isnull=False,
                due_date__lte=today + timedelta(days=3),
                party__reminders_enabled=True,
                party__email__isnull=False,
            )
            .annotate(outstanding=_outstanding())
            .filter(outstanding__gt=0)
            .select_related("party")
            .order_by("due_date", "doc_number")
        )
        done: dict[uuid.UUID, int] = {}
        for row in (
            PaymentReminder.objects.filter(document__in=[b.pk for b in bills])
            .exclude(stage=ReminderStage.MANUAL)
            .values("document_id", "stage")
        ):
            done[row["document_id"]] = max(done.get(row["document_id"], -1), RANK[row["stage"]])
        for bill in bills:
            stage = stage_for(bill.due_date, today)
            if stage is None or done.get(bill.pk, -1) >= RANK[stage]:
                continue  # not yet, or this stage (or a later one) already went out
            email = build_email(bill, bill.party, bill.outstanding, stage, today)
            try:
                with transaction.atomic():  # the log row and the email together
                    PaymentReminder.objects.create(
                        document=bill,
                        stage=stage,
                        sent_to=email.to,
                        amount_due=bill.outstanding,
                    )
                    _send(email)
            except IntegrityError:
                continue  # another run sent it first
            except OSError:
                log.warning("reminder for %s not sent: mail server unreachable", bill.pk)
                continue  # nothing logged: the next run tries again
            sent += 1
    return sent


def send_due_reminders(today: date | None = None) -> int:
    """All active tenants, each on its own "today" (its time zone)."""
    total = 0
    for tenant_id, time_zone in active_tenants():
        try:
            total += send_due_for_tenant(tenant_id, today or tenant_today(time_zone))
        except Exception:
            log.exception("payment reminders failed for tenant %s", tenant_id)
    return total


# --- from the bill ------------------------------------------------------------------


def history(principal: Principal, document_id: uuid.UUID) -> list[PaymentReminder]:
    get_or_404(Document, document_id)  # another tenant's bill: 404
    return list(
        PaymentReminder.objects.filter(document_id=document_id)
        .select_related("sent_by")
        .order_by("-sent_at")
    )


def send_now(principal: Principal, document_id: uuid.UUID) -> PaymentReminder:
    require(principal, SEND)
    with transaction.atomic():
        doc = get_or_404(Document, document_id, for_update=True)  # one at a time per bill
        if doc.status != "ISSUED" or doc.doc_type not in RECEIVABLE_TYPES:
            raise Conflict(
                "Reminders are for issued invoices, bills of supply and debit notes.",
                code="not_receivable",
            )
        outstanding = doc.net_receivable - doc.amount_settled
        if outstanding <= 0:
            raise Conflict("Nothing is outstanding on this bill.", code="nothing_due")
        party = Party.objects.get(pk=doc.party_id)
        if not party.email:
            raise Invalid(
                "party.email",
                "This client has no email address: add one on the client's page.",
                code="no_client_email",
            )
        last = (
            PaymentReminder.objects.filter(document=doc, stage=ReminderStage.MANUAL)
            .order_by("-sent_at")
            .first()
        )
        if last and timezone.now() - last.sent_at < MANUAL_GAP:
            raise Conflict(
                "A reminder for this bill was sent in the last 24 hours.",
                code="reminded_recently",
            )
        email = build_email(doc, party, outstanding, ReminderStage.MANUAL, timezone.localdate())
        reminder: PaymentReminder = PaymentReminder.objects.create(
            document=doc,
            stage=ReminderStage.MANUAL,
            sent_to=email.to,
            amount_due=outstanding,
            sent_by_id=principal.user_id,
        )
        try:
            _send(email)
        except OSError as exc:
            raise EmailUnavailable from exc  # rolls the log row back
    return reminder
