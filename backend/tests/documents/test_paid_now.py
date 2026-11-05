"""Issue a bill and record the money received with it, in one step (Part B).

Each default invoice: 42.5 cum @ 6800 = 289000.00 + 18 % GST = 341020.00; retention
5 % (14450.00) and TDS 1 % (2890.00) come off, so the client pays 323680.00.
"""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.payments.models import Payment
from tests.payments.test_payments import Money

pytestmark = pytest.mark.django_db

NET = "323680.00"


class Counter(Money):
    def issue(self, draft: dict[str, Any], key: str | None = None, **paid: Any) -> Any:
        return APIClient().post(
            f"/api/v1/documents/{draft['id']}/issue",
            {"paid_now": paid} if paid else {},
            format="json",
            **self.h(IF_MATCH=f'"v{draft["version"]}"', IDEMPOTENCY_KEY=key or str(uuid.uuid4())),
        )

    def payments(self) -> list[Payment]:
        with tenant_context(self.t.tenant_id, self.t.user_id):
            return list(Payment.objects.prefetch_related("allocations"))


@pytest.fixture
def c() -> Counter:
    return Counter()


def test_paid_in_full_with_the_bill(c: Counter) -> None:
    draft = c.create().json()
    r = c.issue(draft, amount=NET, mode="CASH", payment_date="2026-10-19")
    assert r.status_code == 200, r.content
    doc = r.json()
    assert (doc["status"], doc["doc_number"]) == ("ISSUED", "INV/0001")
    assert (doc["totals"]["amount_settled"], doc["totals"]["outstanding"]) == (NET, "0.00")
    [payment] = c.payments()
    assert (payment.mode, str(payment.amount), str(payment.payment_date)) == (
        "CASH",
        NET,
        "2026-10-19",
    )
    assert payment.party_id == c.client.pk
    assert payment.project_id == c.project.pk
    assert [(str(a.document_id), str(a.amount)) for a in payment.allocations.all()] == [
        (draft["id"], NET)
    ]


def test_part_paid_and_paid_over_the_bill(c: Counter) -> None:
    part = c.issue(c.create().json(), amount="100000.00", mode="UPI", reference="UPI 123").json()
    assert part["totals"]["outstanding"] == "223680.00"
    over = c.issue(c.create().json(), amount="400000.00", mode="BANK_TRANSFER").json()
    assert over["totals"]["outstanding"] == "0.00"
    extra = next(p for p in c.payments() if p.amount == Decimal("400000.00"))
    allocated = sum(a.amount for a in extra.allocations.all())
    assert extra.amount - allocated == Decimal("76320.00")  # kept as an advance


def test_a_quotation_cannot_be_paid_now_and_stays_a_draft(c: Counter) -> None:
    draft = c.create(doc_type="QUOTATION").json()
    r = c.issue(draft, amount="1000.00", mode="CASH")
    assert r.status_code == 422, r.content
    assert r.json()["errors"][0]["code"] == "not_payable_now"
    again = APIClient().get(f"/api/v1/documents/{draft['id']}", **c.h()).json()
    assert (again["status"], again["doc_number"]) == ("DRAFT", None)  # all or nothing
    assert c.payments() == []
    # the number was not used up: the next quotation issued is still QT/0001
    issued = c.issue(again).json()
    assert issued["doc_number"] == "QT/0001"


def test_one_click_twice_records_one_payment(c: Counter) -> None:
    draft = c.create().json()
    key = str(uuid.uuid4())
    first = c.issue(draft, key=key, amount=NET, mode="CASH")
    second = c.issue(draft, key=key, amount=NET, mode="CASH")
    assert first.status_code == second.status_code == 200
    assert len(c.payments()) == 1


def test_a_bad_payment_is_refused_before_anything_changes(c: Counter) -> None:
    draft = c.create().json()
    r = c.issue(draft, amount="0.00", mode="CASH")
    assert r.status_code == 422, r.content
    assert r.json()["errors"][0]["field"] == "paid_now.amount"
    assert APIClient().get(f"/api/v1/documents/{draft['id']}", **c.h()).json()["status"] == "DRAFT"
