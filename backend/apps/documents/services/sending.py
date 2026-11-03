"""Emailing a bill to its client with the PDF attached (B.15).

The PDF is drawn for the chosen copy (Original for recipient by default),
the email goes out at once, and a `document_emails` row records who sent it
where. If the PDF cannot be drawn or the mail server refuses, nothing is
recorded and the caller gets a 503 to try again.
"""

import uuid

from django.core.mail import EmailMessage
from django.db import transaction
from django.template.loader import render_to_string

from apps.accounts.models import User
from apps.core.errors import Conflict, DomainError, Invalid
from apps.core.permissions import require
from apps.core.queries import get_or_404
from apps.core.tenancy import Principal
from apps.parties.models import Party
from apps.tenants import printing

from ..models import Document, DocumentEmail
from ..pdf.render import PAYABLE, TITLES, inr, render_pdf
from .pdfs import pdf_filename

SEND = "documents.issue"  # sending a bill out is part of issuing it


class PdfUnavailable(DomainError):
    status = 503
    code = "pdf_unavailable"
    detail = "The PDF could not be made just now. Try again in a few minutes."


class EmailUnavailable(DomainError):
    status = 503
    code = "email_unavailable"
    detail = "The email could not be sent just now. Try again in a few minutes."


def _body(doc: Document, party: Party, sender: str, message: str | None) -> str:
    supplier = doc.supplier_snapshot or {}
    settings = supplier.get("print") or printing.snapshot(doc.tenant_id)
    payable = doc.doc_type in PAYABLE and doc.status != "CANCELLED"
    pay = {k: v for k, v in settings.items() if k.startswith("bank_") or k == "upi_id"}
    return render_to_string(
        "documents/email/document.txt",
        {
            "client": party.display_name,
            "title": TITLES[doc.doc_type],
            "number": doc.doc_number,
            "doc_date": doc.doc_date.strftime("%d %b %Y"),
            "amount": inr(doc.net_receivable) if doc.doc_type != "CREDIT_NOTE" else None,
            "due_date": doc.due_date.strftime("%d %b %Y") if doc.due_date and payable else None,
            "message": message,
            "pay": pay if payable and any(pay.values()) else None,
            "sender": sender,
            "company": supplier,
        },
    )


def email_document(
    principal: Principal,
    doc_id: uuid.UUID,
    *,
    to: str | None = None,
    copy: str = "original",
    message: str | None = None,
) -> DocumentEmail:
    require(principal, SEND)
    doc = get_or_404(Document, doc_id)  # another tenant's: 404
    if doc.status == "DRAFT":
        raise Conflict("Issue the bill before sending it.", code="document_not_issued")
    party = Party.objects.get(pk=doc.party_id)
    to = to or (str(party.email) if party.email else None)
    if not to:
        raise Invalid(
            "to",
            "This client has no email address: type one, or add it on the client's page.",
            code="no_client_email",
        )
    user = User.objects.get(pk=principal.user_id)
    try:
        pdf = render_pdf(doc, copy)
    except OSError as exc:  # the renderer's system libraries (or memory) failed
        raise PdfUnavailable from exc
    title = TITLES[doc.doc_type]
    company = (doc.supplier_snapshot or {}).get("legal_name", "")
    email = EmailMessage(
        subject=" ".join(f"{title} {doc.doc_number} from {company}".split()),  # one line
        body=_body(doc, party, user.full_name, message),
        to=[to],
        reply_to=[str(user.email)],  # the client answers the person who sent it
    )
    email.attach(pdf_filename(doc).removesuffix(".pdf") + f"-{copy}.pdf", pdf, "application/pdf")
    with transaction.atomic():
        sent: DocumentEmail = DocumentEmail.objects.create(
            document=doc, sent_to=to, copy=copy, sent_by_id=principal.user_id
        )
        try:
            email.send()
        except OSError as exc:
            raise EmailUnavailable from exc  # rolls the log row back
    return sent
