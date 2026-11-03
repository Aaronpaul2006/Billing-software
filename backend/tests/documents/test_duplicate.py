"""Duplicating a bill or quotation into a new draft (B.10)."""

import uuid
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.parties.models import Party
from tests.documents.test_drafts import RCC
from tests.factories import add_member, make_tenant, owner_member
from tests.payments.test_payments import Money

pytestmark = pytest.mark.django_db

ROWS = [{"description": "Slab", "nos": "2", "length": "5", "breadth": "4.25"}]


@pytest.fixture
def m() -> Money:
    return Money()


def duplicate(
    m: Money, doc: dict[str, Any], doc_date: str = "2026-11-03", member: Any = None
) -> Any:
    return APIClient().post(
        f"/api/v1/documents/{doc['id']}/duplicate",
        {"doc_date": doc_date},
        format="json",
        **m.h(member, IDEMPOTENCY_KEY=str(uuid.uuid4())),
    )


def test_an_issued_bill_becomes_a_new_draft_with_the_same_lines(m: Money) -> None:
    bill = m.invoice(lines=[{**RCC, "measurements": ROWS}, {**RCC, "description": "Beams"}])
    r = duplicate(m, bill)
    assert r.status_code == 201, r.content
    copy = r.json()
    assert copy["id"] != bill["id"]
    assert (copy["status"], copy["doc_number"], copy["doc_date"]) == ("DRAFT", None, "2026-11-03")
    assert (copy["party_id"], copy["project_id"]) == (bill["party_id"], bill["project_id"])
    assert [ln["description"] for ln in copy["lines"]] == [
        ln["description"] for ln in bill["lines"]
    ]
    assert copy["lines"][0]["quantity"] == "42.500"  # 2 x 5 x 4.25
    assert copy["lines"][0]["measurements"][0]["quantity"] == "42.500"
    assert copy["totals"]["grand_total"] == bill["totals"]["grand_total"]
    # the original is untouched
    original = APIClient().get(f"/api/v1/documents/{bill['id']}", **m.h()).json()
    assert original["status"] == "ISSUED"


def test_a_quotation_keeps_its_validity_and_terms_set_the_due_date(m: Money) -> None:
    quote = m.invoice(doc_type="QUOTATION", doc_date="2026-10-01", valid_until="2026-10-31")
    copy = duplicate(m, quote, doc_date="2026-11-03").json()
    assert copy["valid_until"] == "2026-12-03"  # 30 days, as before
    with tenant_context(m.t.tenant_id, m.t.user_id):
        Party.objects.filter(pk=m.client.pk).update(payment_terms_days=15)
    bill = m.invoice(doc_date="2026-10-01", due_date="2026-10-05")
    assert duplicate(m, bill, doc_date="2026-11-03").json()["due_date"] == "2026-11-18"


def test_notes_are_not_duplicated(m: Money) -> None:
    bill = m.invoice()
    r = APIClient().post(
        f"/api/v1/documents/{bill['id']}/credit-notes",
        {"doc_date": "2026-10-30", "lines": [{**RCC, "quantity": "1"}]},
        format="json",
        **m.h(IDEMPOTENCY_KEY=str(uuid.uuid4())),
    )
    assert r.status_code == 201, r.content
    r = duplicate(m, r.json())
    assert (r.status_code, r.json()["code"]) == (409, "not_duplicable")


def test_roles_and_another_tenant(m: Money) -> None:
    bill = m.invoice()
    assert duplicate(m, bill, member=add_member(m.t, "SITE_ENGINEER")).status_code == 201
    assert duplicate(m, bill, member=add_member(m.t, "VIEWER")).status_code == 403


def test_another_tenants_bill_is_not_found(m: Money) -> None:
    bill = m.invoice()
    stranger = owner_member(make_tenant("Stranger Co"))
    assert duplicate(m, bill, member=stranger).status_code == 404
