"""The activity log (Part B): who changed what across the business, owners and admins only."""

import uuid
from typing import Any

import pytest
from rest_framework.test import APIClient

from tests.factories import add_member, make_tenant, owner_member
from tests.payments.test_payments import Money

pytestmark = pytest.mark.django_db


class Shop(Money):
    def log(self, member: Any = None, **query: str) -> Any:
        return APIClient().get("/api/v1/audit-log", query, **self.h(member))


@pytest.fixture
def s() -> Shop:
    return Shop()


def test_says_who_did_what_newest_first(s: Shop) -> None:
    inv = s.invoice()  # created as a draft, then issued
    r = s.pay("100000.00", allocations=[{"document_id": inv["id"], "amount": "100000.00"}])
    assert r.status_code == 201, r.content
    page = s.log()
    assert page.status_code == 200, page.content
    rows = page.json()["results"]
    assert page.json()["next_cursor"] is None
    issued = next(e for e in rows if e["record_type"] == "documents" and e["action"] == "issued")
    assert issued["record"] == "Tax invoice INV/0001"
    assert issued["record_type_label"] == "Bill or quotation"
    assert issued["actor_name"] == "Test User"
    assert issued["changed_fields"] == []  # "issued" says it
    # bookkeeping is not listed: the number series moving on, a PDF being made
    assert not any(e["record_type"] == "document_series" and e["action"] == "changed" for e in rows)
    payment = next(e for e in rows if e["record_type"] == "payments")
    assert (payment["action"], payment["record"]) == ("added", "₹1,00,000.00 on 25 Oct 2026")
    assert [e["id"] for e in rows] == sorted((e["id"] for e in rows), reverse=True)
    # a bill's lines and payment allocations are not listed one by one
    kinds = {e["record_type"] for e in rows}
    assert "document_lines" not in kinds
    assert "allocations" not in kinds
    assert {"documents", "payments", "memberships", "document_series"} <= kinds


def test_filters_by_kind_person_record_and_date(s: Shop) -> None:
    inv = s.invoice()
    only_bills = s.log(record_type="documents").json()["results"]
    assert only_bills
    assert {e["record_type"] for e in only_bills} == {"documents"}
    one = s.log(record_id=inv["id"]).json()["results"]
    assert {e["record_id"] for e in one} == {inv["id"]}
    nobody = s.log(actor_id=str(uuid.uuid4())).json()["results"]
    assert nobody == []
    assert s.log(date_to="2000-01-01").json()["results"] == []
    bad = s.log(record_type="document_lines")
    assert bad.status_code == 422


def test_only_owners_and_admins_see_it(s: Shop) -> None:
    assert s.log(add_member(s.t, "ADMIN")).status_code == 200
    for role in ("ACCOUNTANT", "SITE_ENGINEER", "VIEWER"):
        assert s.log(add_member(s.t, role)).status_code == 403, role


def test_another_business_sees_nothing_of_it(s: Shop) -> None:
    s.invoice()
    other = make_tenant("Other Builders")
    member = owner_member(other)
    r = APIClient().get(
        "/api/v1/audit-log",
        {"record_type": "documents"},
        HTTP_AUTHORIZATION=f"Bearer {member.access_token}",
    )
    assert r.status_code == 200
    assert r.json()["results"] == []
