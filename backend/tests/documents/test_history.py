"""A bill's change history in plain words (B.11)."""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.core.tenancy import tenant_context
from apps.documents.pdf.render import inr
from apps.reminders.models import PaymentReminder
from apps.tenants.models import DocumentSeries
from tests.documents.test_drafts import RCC
from tests.factories import add_member, make_tenant, owner_member
from tests.payments.test_payments import Money

pytestmark = pytest.mark.django_db

BEAMS = {**RCC, "description": "Beams, 1st floor", "quantity": "10.000", "rate": "7000.00"}
COLUMNS = {**RCC, "description": "Columns", "quantity": "5.000"}


@pytest.fixture
def m() -> Money:
    return Money()


def history(m: Money, doc: dict[str, Any], member: Any = None) -> Any:
    return APIClient().get(f"/api/v1/documents/{doc['id']}/history", **m.h(member))


def patch(m: Money, doc: dict[str, Any], version: int, member: Any = None, **body: Any) -> Any:
    r = APIClient().patch(
        f"/api/v1/documents/{doc['id']}",
        body,
        format="json",
        **m.h(member, IF_MATCH=f'"v{version}"'),
    )
    assert r.status_code == 200, r.content
    return r.json()


def act(m: Money, doc: dict[str, Any], action: str, **body: Any) -> Any:
    r = APIClient().post(
        f"/api/v1/documents/{doc['id']}/{action}",
        body,
        format="json",
        **m.h(IF_MATCH=f'"v{doc["version"]}"', IDEMPOTENCY_KEY=str(uuid.uuid4())),
    )
    assert r.status_code == 200, r.content
    return r.json()


def owner_name(m: Money) -> str:
    return str(User.objects.get(pk=m.t.user_id).full_name)


def test_created_edited_issued_and_paid(m: Money) -> None:
    draft = m.create().json()
    patch(
        m,
        draft,
        1,
        due_date="2026-11-18",
        lines=[{**RCC, "rate": "6800.10"}, BEAMS],
    )
    draft = patch(m, draft, 2, notes="RA bill 3")
    issued = act(m, draft, "issue")
    r = m.pay("1000.00", [{"document_id": issued["id"], "amount": "1000.00"}])
    assert r.status_code == 201, r.content

    r = history(m, issued)
    assert r.status_code == 200, r.content
    entries = r.json()["results"]
    assert [e["kind"] for e in entries] == ["payment", "issued", "edited", "created"]
    paid, issue, edit, created = entries
    assert paid["summary"] == "Payment received: ₹1,000.00"
    assert paid["details"] == [
        "Payment of ₹1,000.00 on 25 Oct 2026",
        "bank transfer, UTR SBIN0026102500123",
    ]
    assert issue["summary"] == "Issued as INV/0001"
    assert issue["details"][0] == f"Total ₹{_inr(issued['totals']['grand_total'])}"
    # two saves by one person, minutes apart: one entry, the net change
    assert edit["summary"] == "Edited the draft"
    assert edit["details"][:2] == ["Due date: none → 18 Nov 2026", 'Notes: none → "RA bill 3"']
    assert edit["details"][2].startswith("Total: ₹3,41,020.00 → ")
    assert edit["details"][3:] == [
        'Line 1 "RCC M25 for slab, 2nd floor": rate ₹6,800.00 → ₹6,800.10',
        'Added line 2 "Beams, 1st floor": 10 cum at ₹7,000.00',
    ]
    assert created["summary"] == "Created the draft tax invoice"
    assert created["details"] == ["1 line, total ₹3,41,020.00"]
    assert {e["actor_name"] for e in entries} == {owner_name(m)}


def _inr(amount: str) -> str:
    return inr(Decimal(amount))


def test_removing_a_line_is_one_change_not_a_change_to_every_line_below(m: Money) -> None:
    draft = m.create(lines=[RCC, BEAMS, COLUMNS]).json()
    patch(m, draft, 1, lines=[RCC, {**COLUMNS, "quantity": "6"}])
    edit = history(m, draft).json()["results"][0]
    lines = [d for d in edit["details"] if not d.startswith("Total")]
    assert lines == [
        'Removed line 2 "Beams, 1st floor"',
        'Line 2 "Columns": quantity 5 → 6',
    ]


def test_cancelled_with_the_reason_and_edits_by_others_kept_apart(m: Money) -> None:
    accountant = add_member(m.t, "ACCOUNTANT")
    draft = m.create().json()
    draft = patch(m, draft, 1, member=accountant, notes="Checked")
    issued = act(m, draft, "issue")
    act(m, issued, "cancel", reason="Wrong client")
    entries = history(m, issued).json()["results"]
    assert [(e["kind"], e["actor_name"]) for e in entries] == [
        ("cancelled", owner_name(m)),
        ("issued", owner_name(m)),
        ("edited", "Accountant User"),
        ("created", owner_name(m)),
    ]
    assert entries[0]["details"] == ["Reason: Wrong client"]


def test_a_quotation_accepted_and_converted(m: Money) -> None:
    quote = m.invoice(doc_type="QUOTATION", valid_until="2026-11-30")
    accepted = act(m, quote, "accept")
    r = APIClient().post(
        f"/api/v1/documents/{quote['id']}/convert",
        {"to": "TAX_INVOICE", "doc_date": "2026-11-03"},
        format="json",
        **m.h(IDEMPOTENCY_KEY=str(uuid.uuid4())),
    )
    assert r.status_code == 201, r.content
    entries = history(m, accepted).json()["results"]
    assert [e["summary"] for e in entries] == [
        "Made into a draft tax invoice",
        "Marked as accepted by the client",
        "Issued as QT/0001",
        "Created the draft quotation",
    ]
    made = history(m, r.json()).json()["results"]
    assert made[-1]["details"][0] == "Made from quotation QT/0001"


def test_everyone_who_can_see_the_bill_sees_its_history(m: Money) -> None:
    bill = m.invoice()
    assert history(m, bill, member=add_member(m.t, "VIEWER")).status_code == 200
    assert history(m, bill, member=add_member(m.t, "SITE_ENGINEER")).status_code == 200


def test_another_tenants_bill_is_not_found(m: Money) -> None:
    bill = m.invoice()
    stranger = owner_member(make_tenant("Stranger Co"))
    assert history(m, bill, member=stranger).status_code == 404


def test_credit_notes_and_reminders_show_on_the_bill(m: Money) -> None:
    bill = m.invoice()
    r = APIClient().post(
        f"/api/v1/documents/{bill['id']}/credit-notes",
        {"doc_date": "2026-10-30", "lines": [{**RCC, "quantity": "1"}]},
        format="json",
        **m.h(IDEMPOTENCY_KEY=str(uuid.uuid4())),
    )
    assert r.status_code == 201, r.content
    note = r.json()
    with tenant_context(m.t.tenant_id, m.t.user_id):
        DocumentSeries.objects.create(
            gst_registration_id=m.t.registration_id,
            doc_type="CREDIT_NOTE",
            fy_start_year=2026,
            prefix="CN/",
        )
    act(m, note, "issue")
    with tenant_context(m.t.tenant_id, m.t.user_id):
        PaymentReminder.objects.create(
            document_id=bill["id"],
            stage="MANUAL",
            sent_to="accounts@skyline.example",
            amount_due=Decimal("100.00"),
            sent_by_id=m.t.user_id,
        )
    summaries = [e["summary"] for e in history(m, bill).json()["results"]]
    assert summaries[:2] == [
        "Payment reminder emailed to accounts@skyline.example",
        "Credit note CN/0001 issued against this bill",
    ]
