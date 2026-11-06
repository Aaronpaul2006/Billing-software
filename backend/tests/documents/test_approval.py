"""Bill approval (Part B): above the limit, others need an owner's approval of
the version they issue. The default draft is 42.5 cum of RCC: 3,41,020.00."""

import uuid
from typing import Any

import pytest
from rest_framework.test import APIClient

from tests.factories import Member, add_member
from tests.payments.test_payments import Money

pytestmark = pytest.mark.django_db


class Office(Money):
    def __init__(self) -> None:
        super().__init__()
        self.accountant = add_member(self.t, "ACCOUNTANT")

    def set_limit(self, amount: str | None) -> None:
        tenant = APIClient().get("/api/v1/tenant", **self.h()).json()
        r = APIClient().patch(
            "/api/v1/tenant",
            {"approval_limit": amount},
            format="json",
            **self.h(IF_MATCH=f'"v{tenant["version"]}"'),
        )
        assert r.status_code == 200, r.content
        assert r.json()["approval_limit"] == amount

    def act(self, doc: dict[str, Any], action: str, member: Member | None = None) -> Any:
        return APIClient().post(
            f"/api/v1/documents/{doc['id']}/{action}",
            {},
            format="json",
            **self.h(member, IF_MATCH=f'"v{doc["version"]}"', IDEMPOTENCY_KEY=str(uuid.uuid4())),
        )

    def bell(self, member: Member | None = None) -> list[dict[str, Any]]:
        return list(APIClient().get("/api/v1/notifications", **self.h(member)).json()["results"])


@pytest.fixture
def o() -> Office:
    return Office()


def code(r: Any) -> str:
    return str(r.json()["code"])


def test_ask_approve_then_issue(o: Office) -> None:
    o.set_limit("100000.00")
    draft = o.create().json()
    r = o.act(draft, "issue", o.accountant)
    assert (r.status_code, code(r)) == (409, "approval_required")
    assert "₹1,00,000.00 or more" in r.json()["detail"]

    asked = o.act(draft, "approval-request", o.accountant)
    assert asked.status_code == 200, asked.content
    assert asked.json()["approval_requested_at"] is not None
    assert asked.json()["approval_holds"] is False
    bell = o.bell()
    assert [n["kind"] for n in bell] == ["APPROVAL_REQUESTED"]
    assert bell[0]["link"] == f"/documents/{draft['id']}"

    r = o.act(draft, "approve", o.accountant)
    assert (r.status_code, code(r)) == (403, "approver_only")
    approved = o.act(draft, "approve")
    assert approved.status_code == 200, approved.content
    assert approved.json()["approval_holds"] is True
    assert approved.json()["version"] == draft["version"]  # approving is not an edit
    assert [n["kind"] for n in o.bell(o.accountant)] == ["BILL_APPROVED"]

    issued = o.act(approved.json(), "issue", o.accountant)
    assert issued.status_code == 200, issued.content
    assert issued.json()["status"] == "ISSUED"


def test_an_edit_after_approval_needs_a_new_one(o: Office) -> None:
    o.set_limit("100000.00")
    draft = o.create().json()
    o.act(draft, "approve")
    edited = APIClient().patch(
        f"/api/v1/documents/{draft['id']}",
        {"notes": "Second floor slab"},
        format="json",
        **o.h(o.accountant, IF_MATCH=f'"v{draft["version"]}"'),
    )
    assert edited.status_code == 200, edited.content
    assert edited.json()["approval_holds"] is False
    r = o.act(edited.json(), "issue", o.accountant)
    assert (r.status_code, code(r)) == (409, "approval_required")


def test_owners_below_the_limit_and_no_limit_need_none(o: Office) -> None:
    o.set_limit("100000.00")
    assert o.act(o.create().json(), "issue").status_code == 200  # an owner issues
    o.set_limit("500000.00")
    assert o.act(o.create().json(), "issue", o.accountant).status_code == 200  # below it
    o.set_limit(None)
    assert o.act(o.create().json(), "issue", o.accountant).status_code == 200  # no limit


def test_quotations_need_none(o: Office) -> None:
    o.set_limit("100000.00")
    quote = o.create(doc_type="QUOTATION", valid_until="2027-03-31").json()
    assert o.act(quote, "issue", o.accountant).status_code == 200


def test_another_business_reaches_none_of_it(o: Office) -> None:
    draft = o.create().json()
    other = Office()
    for action in ("approval-request", "approve"):
        assert o.act(draft, action, other.owner).status_code == 404
