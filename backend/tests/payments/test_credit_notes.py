"""Applying issued credit notes to invoices (Phase 2.2)."""

import uuid
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.parties.models import Party
from apps.tenants.models import DocumentSeries
from tests.documents.test_drafts import RCC

from .test_payments import Money, problem

pytestmark = pytest.mark.django_db


class Credits(Money):
    def __init__(self) -> None:
        super().__init__()
        with tenant_context(self.t.tenant_id, self.t.user_id):
            DocumentSeries.objects.create(
                gst_registration_id=self.t.registration_id,
                doc_type="CREDIT_NOTE",
                fy_start_year=2026,
                prefix="CN/",
            )

    def credit_note(
        self, invoice: dict[str, Any], quantity: str = "1", issue: bool = True
    ) -> dict[str, Any]:
        """A credit note for `quantity` cum of the RCC line (1 cum = 6800 + 18 % = 8024.00)."""
        r = APIClient().post(
            f"/api/v1/documents/{invoice['id']}/credit-notes",
            {"doc_date": "2026-10-30", "lines": [{**RCC, "quantity": quantity}]},
            format="json",
            **self.h(IDEMPOTENCY_KEY=str(uuid.uuid4())),
        )
        assert r.status_code == 201, r.content
        note = dict(r.json())
        if issue:
            r = APIClient().post(
                f"/api/v1/documents/{note['id']}/issue",
                {},
                format="json",
                **self.h(IF_MATCH='"v1"', IDEMPOTENCY_KEY=str(uuid.uuid4())),
            )
            assert r.status_code == 200, r.content
            note = dict(r.json())
        return note

    def apply(self, note_id: str, allocations: list[dict[str, str]]) -> Any:
        return APIClient().post(
            f"/api/v1/documents/{note_id}/allocations",
            {"allocations": allocations},
            format="json",
            **self.h(IDEMPOTENCY_KEY=str(uuid.uuid4())),
        )

    def allocations(self, doc_id: str) -> dict[str, Any]:
        return dict(APIClient().get(f"/api/v1/documents/{doc_id}/allocations", **self.h()).json())


@pytest.fixture
def c() -> Credits:
    return Credits()


def test_apply_a_credit_note_to_its_invoice(c: Credits) -> None:
    invoice = c.invoice()
    note = c.credit_note(invoice)
    assert note["totals"]["grand_total"] == "8024.00"

    r = c.apply(note["id"], [{"document_id": invoice["id"], "amount": "8024.00"}])
    assert r.status_code == 200, r.content
    assert (r.json()["applied"], r.json()["unapplied"]) == ("8024.00", "0.00")
    assert c.totals(invoice["id"])["outstanding"] == "315656.00"  # 323680 - 8024

    settled_by = c.allocations(invoice["id"])
    assert settled_by["applied"] is None  # not a credit note
    assert [a["credit_note_id"] for a in settled_by["allocations"]] == [note["id"]]


def test_credit_and_payment_together_settle_an_invoice(c: Credits) -> None:
    invoice = c.invoice()
    note = c.credit_note(invoice, quantity="2")  # 16048.00
    c.apply(note["id"], [{"document_id": invoice["id"], "amount": "16048.00"}])
    c.pay("307632.00", [{"document_id": invoice["id"], "amount": "307632.00"}])
    assert c.totals(invoice["id"])["outstanding"] == "0.00"
    sources = c.allocations(invoice["id"])["allocations"]
    assert sorted(bool(a["payment_id"]) for a in sources) == [False, True]


def test_limits(c: Credits) -> None:
    invoice = c.invoice()
    note = c.credit_note(invoice)  # 8024.00
    assert problem(c.apply(note["id"], [{"document_id": invoice["id"], "amount": "8024.01"}])) == (
        422,
        "allocation_exceeds_credit",
    )
    small = c.invoice(lines=[{**RCC, "quantity": "0.001"}])  # net 7.03
    assert problem(c.apply(note["id"], [{"document_id": small["id"], "amount": "8.00"}])) == (
        422,
        "allocation_exceeds_outstanding",
    )
    # spread over two invoices of the same party
    split = c.apply(
        note["id"],
        [
            {"document_id": small["id"], "amount": "7.03"},
            {"document_id": invoice["id"], "amount": "8016.97"},
        ],
    )
    assert split.status_code == 200, split.content
    assert split.json()["unapplied"] == "0.00"
    again = c.apply(note["id"], [{"document_id": invoice["id"], "amount": "0.01"}])
    assert problem(again) == (422, "allocation_exceeds_credit")


def test_only_issued_credit_notes_are_applied(c: Credits) -> None:
    invoice = c.invoice()
    draft = c.credit_note(invoice, issue=False)
    assert problem(c.apply(draft["id"], [{"document_id": invoice["id"], "amount": "1.00"}])) == (
        409,
        "not_an_issued_credit_note",
    )
    assert problem(c.apply(invoice["id"], [{"document_id": invoice["id"], "amount": "1.00"}])) == (
        409,
        "not_an_issued_credit_note",
    )


def test_party_and_settleability_rules(c: Credits) -> None:
    invoice = c.invoice()
    note = c.credit_note(invoice)
    quote = c.invoice(doc_type="QUOTATION")
    assert problem(c.apply(note["id"], [{"document_id": quote["id"], "amount": "1.00"}])) == (
        422,
        "document_not_settleable",
    )
    assert problem(c.apply(note["id"], [{"document_id": note["id"], "amount": "1.00"}])) == (
        422,
        "document_not_settleable",  # a credit note cannot settle itself
    )
    with tenant_context(c.t.tenant_id, c.t.user_id):
        other = Party.objects.create(
            display_name="Other", gst_treatment="UNREGISTERED", created_by_id=c.t.user_id
        )
        project = c.make_project("OTHER-1", "32")
        project.client_party_id = other.pk
        project.save(update_fields=["client_party"])
    foreign = c.invoice(party_id=str(other.pk), project_id=str(project.pk))
    assert problem(c.apply(note["id"], [{"document_id": foreign["id"], "amount": "1.00"}])) == (
        422,
        "party_mismatch",
    )


def test_unwind_then_cancel_the_credit_note(c: Credits) -> None:
    invoice = c.invoice()
    note = c.credit_note(invoice)
    applied = c.apply(note["id"], [{"document_id": invoice["id"], "amount": "8024.00"}]).json()
    cancel_url = f"/api/v1/documents/{note['id']}/cancel"
    blocked = APIClient().post(
        cancel_url, {"reason": "wrong rate"}, format="json", **c.h(IF_MATCH=f'"v{note["version"]}"')
    )
    assert problem(blocked) == (409, "credit_note_allocated")
    allocation = applied["allocations"][0]["id"]
    assert APIClient().delete(f"/api/v1/allocations/{allocation}", **c.h()).status_code == 204
    assert c.totals(invoice["id"])["outstanding"] == "323680.00"
    ok = APIClient().post(
        cancel_url, {"reason": "wrong rate"}, format="json", **c.h(IF_MATCH=f'"v{note["version"]}"')
    )
    assert ok.status_code == 200
