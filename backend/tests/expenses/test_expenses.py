"""Expenses (Phase 2.3)."""

import uuid
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.expenses.models import Expense
from apps.parties.models import Party
from tests.documents.test_drafts import World
from tests.factories import add_member

pytestmark = pytest.mark.django_db


class Costs(World):
    def __init__(self) -> None:
        super().__init__()
        with tenant_context(self.t.tenant_id, self.t.user_id):
            self.vendor = Party.objects.create(
                display_name="Coastal Cement",
                gst_treatment="UNREGISTERED",
                is_customer=False,
                is_vendor=True,
                created_by_id=self.t.user_id,
            )

    def record(self, member: Any = None, key: str | None = None, **body: Any) -> Any:
        payload = {
            "project_id": str(self.project.pk),
            "vendor_party_id": str(self.vendor.pk),
            "category": "MATERIAL",
            "expense_date": "2026-10-20",
            "description": "100 bags OPC 53",
            "vendor_bill_number": "CC/2231",
            "taxable_value": "38000.00",
            "gst_amount": "10640.00",
            **body,
        }
        return APIClient().post(
            "/api/v1/expenses",
            payload,
            format="json",
            **self.h(member, IDEMPOTENCY_KEY=key or str(uuid.uuid4())),
        )


@pytest.fixture
def c() -> Costs:
    return Costs()


def problem(r: Any) -> tuple[int, str]:
    b = r.json()
    return r.status_code, (b["errors"][0]["code"] if b["code"] == "validation_error" else b["code"])


def test_record_an_expense_the_server_computes_the_total(c: Costs) -> None:
    r = c.record(itc_eligible=True, total_amount="1.00")  # a client total is ignored
    assert r.status_code == 201, r.content
    body = r.json()
    assert (body["total_amount"], body["amount_paid"], body["balance"]) == (
        "48640.00",
        "0.00",
        "48640.00",
    )
    assert (body["status"], body["itc_eligible"], r["ETag"]) == ("RECORDED", True, '"v1"')


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"amount_paid": "50000.00", "payment_mode": "CASH"}, "exceeds_total"),
        ({"amount_paid": "100.00"}, "required"),  # paid, but how?
        ({"gst_amount": "0.00", "itc_eligible": True}, "no_gst"),
        ({"taxable_value": 38000}, "not_a_string"),
        ({"category": "SNACKS"}, "invalid_choice"),
        ({"project_id": str(uuid.uuid4())}, "not_found"),
    ],
)
def test_validation(c: Costs, body: dict[str, Any], code: str) -> None:
    assert problem(c.record(**body)) == (422, code)


def test_vendor_must_be_a_vendor(c: Costs) -> None:
    assert problem(c.record(vendor_party_id=str(c.client.pk))) == (422, "not_a_vendor")


def test_edit_payment_status_then_void(c: Costs) -> None:
    expense = c.record().json()
    url, api = f"/api/v1/expenses/{expense['id']}", APIClient()
    paid = api.patch(
        url,
        {"amount_paid": "20000.00", "payment_mode": "UPI"},
        format="json",
        **c.h(IF_MATCH='"v1"'),
    )
    assert paid.status_code == 200, paid.content
    assert (paid.json()["balance"], paid["ETag"]) == ("28640.00", '"v2"')
    # merged validation: lowering the taxable value below what was paid
    assert problem(
        api.patch(
            url,
            {"taxable_value": "1000.00", "gst_amount": "0.00"},
            format="json",
            **c.h(IF_MATCH='"v2"'),
        )
    ) == (422, "exceeds_total")

    voided = api.post(f"{url}/void", {}, format="json", **c.h(IF_MATCH='"v2"'))
    assert voided.json()["status"] == "VOIDED"
    assert problem(api.patch(url, {"description": "x"}, format="json", **c.h(IF_MATCH='"v3"'))) == (
        409,
        "expense_voided",
    )
    assert problem(api.post(f"{url}/void", {}, format="json", **c.h(IF_MATCH='"v3"'))) == (
        409,
        "expense_voided",
    )
    assert api.delete(url, **c.h()).status_code == 405  # never deleted


def test_site_engineers_record_expenses_viewers_only_read(c: Costs) -> None:
    assert c.record(member=add_member(c.t, "SITE_ENGINEER")).status_code == 201
    viewer = add_member(c.t, "VIEWER")
    assert problem(c.record(member=viewer)) == (403, "permission_denied")
    assert APIClient().get("/api/v1/expenses", **c.h(viewer)).status_code == 200


def test_idempotent_create_and_filters(c: Costs) -> None:
    key = str(uuid.uuid4())
    c.record(key=key)
    assert c.record(key=key)["Idempotent-Replayed"] == "true"
    c.record(
        category="LABOUR",
        description="Masons, week 42",
        vendor_party_id=None,
        gst_amount="0.00",
        taxable_value="42000.00",
        amount_paid="42000.00",
        payment_mode="CASH",
        expense_date="2026-10-25",
    )
    with tenant_context(c.t.tenant_id, c.t.user_id):
        assert Expense.objects.count() == 2
    api = APIClient()

    def descriptions(**q: str) -> list[str]:
        rows = api.get("/api/v1/expenses", q, **c.h()).json()["results"]
        return sorted(r["description"] for r in rows)

    assert descriptions(category="LABOUR,EQUIPMENT") == ["Masons, week 42"]
    assert descriptions(payment_state="PAID") == ["Masons, week 42"]
    assert descriptions(payment_state="UNPAID") == ["100 bags OPC 53"]
    assert descriptions(expense_date_from="2026-10-21") == ["Masons, week 42"]
    assert descriptions(vendor_party_id=str(c.vendor.pk)) == ["100 bags OPC 53"]
