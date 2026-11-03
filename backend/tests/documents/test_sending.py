"""Emailing a bill with its PDF to the client (B.15)."""

import uuid
from typing import Any

import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.core.tenancy import tenant_context
from apps.documents.models import Document, DocumentEmail
from apps.documents.services import sending
from apps.parties.models import Party
from apps.tenants.models import PrintSettings
from tests.factories import add_member, make_tenant, owner_member
from tests.payments.test_payments import Money

pytestmark = pytest.mark.django_db
FAKE_PDF = b"%PDF-1.7 bill"


@pytest.fixture
def m(monkeypatch: pytest.MonkeyPatch) -> Money:
    drawn: list[str | None] = []

    def fake(doc: Document, copy: str | None = None) -> bytes:
        drawn.append(copy)
        return FAKE_PDF

    monkeypatch.setattr(sending, "render_pdf", fake)
    world = Money()
    world.drawn = drawn  # type: ignore[attr-defined]
    with tenant_context(world.t.tenant_id, world.t.user_id):
        Party.objects.filter(pk=world.client.pk).update(email="accounts@skyline.example")
    return world


def send(m: Money, doc: dict[str, Any], member: Any = None, **body: Any) -> Any:
    return APIClient().post(
        f"/api/v1/documents/{doc['id']}/email",
        body,
        format="json",
        **m.h(member, IDEMPOTENCY_KEY=str(uuid.uuid4())),
    )


def test_the_bill_goes_to_the_client_with_its_pdf(m: Money) -> None:
    with tenant_context(m.t.tenant_id, m.t.user_id):
        PrintSettings.objects.create(
            tenant_id=m.t.tenant_id, bank_ifsc="SBIN0070123", upi_id="nair@okaxis"
        )
    bill = m.invoice(due_date="2026-11-18")
    r = send(m, bill, message="RA bill 3 as discussed.")
    assert r.status_code == 201, r.content
    assert (r.json()["sent_to"], r.json()["copy"]) == ("accounts@skyline.example", "original")
    assert m.drawn == ["original"]  # type: ignore[attr-defined]
    [email] = mail.outbox
    assert email.to == ["accounts@skyline.example"]
    assert email.subject.startswith("Tax Invoice INV/0001 from ")
    assert email.attachments == [("tax_invoice-INV-0001-original.pdf", FAKE_PDF, "application/pdf")]
    owner = User.objects.get(pk=m.t.user_id)
    assert email.reply_to == [owner.email]  # the client answers the person who sent it
    body = email.body
    assert "Please find attached our tax invoice INV/0001 dated 19 Oct 2026 for ₹" in body
    assert "Payment is due by 18 Nov 2026." in body
    assert "RA bill 3 as discussed." in body
    assert "IFSC: SBIN0070123" in body
    assert "UPI: nair@okaxis" in body
    # recorded, and shown in the bill's history
    history = APIClient().get(f"/api/v1/documents/{bill['id']}/history", **m.h()).json()
    assert history["results"][0]["summary"] == "Emailed to accounts@skyline.example"


def test_another_address_and_copy(m: Money) -> None:
    bill = m.invoice()
    r = send(m, bill, to="site.office@skyline.example", copy="duplicate")
    assert r.status_code == 201, r.content
    assert mail.outbox[0].to == ["site.office@skyline.example"]
    assert mail.outbox[0].attachments[0][0] == "tax_invoice-INV-0001-duplicate.pdf"


def test_drafts_and_clients_without_email(m: Money) -> None:
    draft = m.create().json()
    r = send(m, draft)
    assert (r.status_code, r.json()["code"]) == (409, "document_not_issued")
    bill = m.invoice()
    with tenant_context(m.t.tenant_id, m.t.user_id):
        Party.objects.filter(pk=m.client.pk).update(email=None)
    r = send(m, bill)
    assert (r.status_code, r.json()["errors"][0]["code"]) == (422, "no_client_email")
    assert mail.outbox == []


def test_a_failed_send_records_nothing(m: Money, monkeypatch: pytest.MonkeyPatch) -> None:
    bill = m.invoice()

    def refuse(self: Any, fail_silently: bool = False) -> int:
        raise OSError("connection refused")

    monkeypatch.setattr("django.core.mail.EmailMessage.send", refuse)
    r = send(m, bill)
    assert (r.status_code, r.json()["code"]) == (503, "email_unavailable")
    with tenant_context(m.t.tenant_id, m.t.user_id):
        assert not DocumentEmail.objects.exists()


def test_roles(m: Money) -> None:
    bill = m.invoice()
    assert send(m, bill, member=add_member(m.t, "ACCOUNTANT")).status_code == 201
    assert send(m, bill, member=add_member(m.t, "SITE_ENGINEER")).status_code == 403
    assert send(m, bill, member=add_member(m.t, "VIEWER")).status_code == 403


def test_another_tenants_bill_is_not_found(m: Money) -> None:
    bill = m.invoice()
    stranger = owner_member(make_tenant("Stranger Co"))
    assert send(m, bill, member=stranger).status_code == 404
    assert mail.outbox == []
