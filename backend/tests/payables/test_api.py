"""Payables API (Part B): vendor bills with the TDS we deduct, payments to vendors,
what we owe by age.

A typical bill: 50000.00 + 18 % GST = 59000.00; TDS 194C 1 % on the value before
GST = 500.00; we pay the vendor 58500.00.
"""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.parties.models import Party
from apps.projects.models import Project
from tests.factories import Member, add_member, make_tenant, owner_member

pytestmark = pytest.mark.django_db


class Books:
    def __init__(self, name: str = "Nair Constructions") -> None:
        self.t = make_tenant(name)
        self.owner = owner_member(self.t)
        with tenant_context(self.t.tenant_id, self.t.user_id):
            self.vendor = self.party("Ravi Kumar (labour contractor)", pan="ABCPK1234L")
            self.firm = self.party("Kerala Steel Traders", pan="AAACK1234M")
            self.client = Party.objects.create(
                display_name="Skyline Developers",
                gst_treatment="UNREGISTERED",
                created_by_id=self.t.user_id,
            )
            self.project = Project.objects.create(
                code="VILLA-1",
                name="Villa",
                client_party=self.client,
                gst_registration_id=self.t.registration_id,
                site_state_code="32",
                created_by_id=self.t.user_id,
            )

    def party(self, name: str, pan: str | None = None) -> Party:
        party: Party = Party.objects.create(
            display_name=name,
            gst_treatment="UNREGISTERED",
            is_customer=False,
            is_vendor=True,
            pan=pan,
            created_by_id=self.t.user_id,
        )
        return party

    def h(self, member: Member | None = None, **extra: str) -> dict[str, Any]:
        m = member or self.owner
        return {
            "HTTP_AUTHORIZATION": f"Bearer {m.access_token}",
            **{f"HTTP_{k}": v for k, v in extra.items()},
        }

    def bill(self, member: Member | None = None, **body: Any) -> Any:
        payload = {
            "vendor_party_id": str(self.vendor.pk),
            "project_id": str(self.project.pk),
            "bill_number": f"RK/{uuid.uuid4().hex[:6]}",
            "bill_date": "2026-10-10",
            "due_date": "2026-10-25",
            "category": "SUBCONTRACT",
            "description": "Brickwork, ground floor",
            "taxable_value": "50000.00",
            "gst_amount": "9000.00",
            "tds_section": "194C",
            "tds_rate": "1.00",
            **body,
        }
        return APIClient().post(
            "/api/v1/vendor-bills",
            payload,
            format="json",
            **self.h(member, IDEMPOTENCY_KEY=str(uuid.uuid4())),
        )

    def pay(self, amount: str, allocations: list[dict[str, str]], **body: Any) -> Any:
        payload = {
            "vendor_party_id": str(self.vendor.pk),
            "payment_date": "2026-10-28",
            "amount": amount,
            "mode": "BANK_TRANSFER",
            "reference": "UTR 1234",
            "allocations": allocations,
            **body,
        }
        return APIClient().post(
            "/api/v1/vendor-payments",
            payload,
            format="json",
            **self.h(IDEMPOTENCY_KEY=str(uuid.uuid4())),
        )

    def get(self, url: str, member: Member | None = None, **query: Any) -> Any:
        return APIClient().get(url, query, **self.h(member))

    def post(self, url: str, body: dict[str, Any], version: int) -> Any:
        return APIClient().post(url, body, format="json", **self.h(IF_MATCH=f'"v{version}"'))


@pytest.fixture
def b() -> Books:
    return Books()


def err(r: Any) -> tuple[int, str]:
    body = r.json()
    code = body["errors"][0]["code"] if body["code"] == "validation_error" else body["code"]
    return r.status_code, code


def test_a_bill_works_out_its_tds_and_what_we_pay(b: Books) -> None:
    r = b.bill(bill_number="RK/101")
    assert r.status_code == 201, r.content
    bill = r.json()
    assert (bill["total_amount"], bill["tds_amount"], bill["net_payable"]) == (
        "59000.00",
        "500.00",
        "58500.00",
    )
    assert (bill["outstanding"], bill["vendor_name"], bill["tds_rate"]) == (
        "58500.00",
        "Ravi Kumar (labour contractor)",
        "1.00",
    )
    assert err(b.bill(bill_number="rk/101")) == (422, "duplicate")  # one number per vendor
    assert err(b.bill(vendor_party_id=str(b.client.pk))) == (422, "not_a_vendor")
    assert err(b.bill(tds_section=None, tds_rate="2.00")) == (422, "required")
    assert err(b.bill(due_date="2026-10-01")) == (422, "invalid")
    no_tds = b.bill(tds_section=None, tds_rate=None).json()
    assert (no_tds["tds_amount"], no_tds["net_payable"]) == ("0.00", "59000.00")


def test_tds_suggestion_follows_the_limits_and_the_pan(b: Books) -> None:
    def ask(vendor: Party, value: str, category: str = "SUBCONTRACT") -> dict[str, Any]:
        r = b.get(
            "/api/v1/vendor-bills/tds-suggestion",
            vendor_party_id=str(vendor.pk),
            category=category,
            taxable_value=value,
            bill_date="2026-10-10",
        )
        assert r.status_code == 200, r.content
        return dict(r.json())

    small = ask(b.vendor, "25000.00")
    assert (small["section"], small["amount"]) == (None, "0.00")
    assert "Below the 194C limits" in small["reason"]
    person = ask(b.vendor, "50000.00")
    assert (person["section"], person["rate"], person["amount"]) == ("194C", "1.00", "500.00")
    firm = ask(b.firm, "50000.00")
    assert (firm["rate"], firm["amount"]) == ("2.00", "1000.00")
    with tenant_context(b.t.tenant_id, b.t.user_id):
        no_pan = b.party("Anil Transport")
    assert ask(no_pan, "50000.00")["rate"] == "20.00"
    assert ask(b.firm, "500000.00", "MATERIAL")["section"] is None  # material: no 194C
    # the year limit: 80000 already this year + 25000 passes 1,00,000
    for _ in range(2):
        assert b.bill(taxable_value="40000.00", tds_section=None, tds_rate=None).status_code == 201
    year = ask(b.vendor, "25000.00")
    assert (year["section"], year["year_total"]) == ("194C", "80000.00")


def test_one_payment_settles_several_bills(b: Books) -> None:
    first = b.bill(bill_date="2026-10-01", due_date="2026-10-15").json()
    second = b.bill().json()
    r = b.pay(
        "100000.00",
        [
            {"vendor_bill_id": first["id"], "amount": "58500.00"},
            {"vendor_bill_id": second["id"], "amount": "30000.00"},
        ],
    )
    assert r.status_code == 201, r.content
    payment = r.json()
    assert payment["unallocated"] == "11500.00"
    assert [a["bill_number"] for a in payment["allocations"]] == [
        first["bill_number"],
        second["bill_number"],
    ]
    paid = b.get(f"/api/v1/vendor-bills/{first['id']}").json()
    part = b.get(f"/api/v1/vendor-bills/{second['id']}").json()
    assert (paid["outstanding"], part["outstanding"]) == ("0.00", "28500.00")
    open_bills = b.get("/api/v1/vendor-bills", payment_state="OPEN").json()["results"]
    assert [x["id"] for x in open_bills] == [second["id"]]
    over = b.pay("40000.00", [{"vendor_bill_id": second["id"], "amount": "30000.00"}])
    assert err(over) == (422, "exceeds_outstanding")
    firm_bill = b.bill(vendor_party_id=str(b.firm.pk)).json()
    wrong = b.pay("1000.00", [{"vendor_bill_id": firm_bill["id"], "amount": "1000.00"}])
    assert err(wrong) == (422, "party_mismatch")


def test_edit_until_paid_then_void_in_order(b: Books) -> None:
    bill = b.bill().json()
    url = f"/api/v1/vendor-bills/{bill['id']}"
    edited = APIClient().patch(
        url,
        {"taxable_value": "60000.00", "gst_amount": "10800.00"},
        format="json",
        **b.h(IF_MATCH='"v1"'),
    )
    assert edited.status_code == 200, edited.content
    assert (edited.json()["tds_amount"], edited.json()["net_payable"]) == ("600.00", "70200.00")
    payment = b.pay("70200.00", [{"vendor_bill_id": bill["id"], "amount": "70200.00"}]).json()
    again = APIClient().patch(url, {"description": "x"}, format="json", **b.h(IF_MATCH='"v2"'))
    assert err(again) == (409, "vendor_bill_paid")
    assert err(b.post(f"{url}/void", {"reason": "entered twice"}, 2)) == (409, "vendor_bill_paid")
    voided = b.post(f"/api/v1/vendor-payments/{payment['id']}/void", {"reason": "bounced"}, 1)
    assert voided.status_code == 200, voided.content
    assert (voided.json()["status"], voided.json()["allocations"]) == ("VOIDED", [])
    assert b.get(url).json()["outstanding"] == "70200.00"
    gone = b.post(f"{url}/void", {"reason": "entered twice"}, 2)
    assert gone.status_code == 200, gone.content
    assert (gone.json()["status"], gone.json()["outstanding"]) == ("VOIDED", "0.00")


def test_what_we_owe_by_age(b: Books) -> None:
    today = timezone.localdate()
    late = b.bill(
        bill_date=str(today - timedelta(days=50)), due_date=str(today - timedelta(days=40))
    ).json()
    b.bill(bill_date=str(today), due_date=str(today + timedelta(days=15)))
    b.bill(vendor_party_id=str(b.firm.pk), bill_date=str(today), due_date=None)
    b.pay("8500.00", [{"vendor_bill_id": late["id"], "amount": "8500.00"}])
    r = b.get("/api/v1/reports/payables")
    assert r.status_code == 200, r.content
    report = r.json()
    ravi = next(x for x in report["results"] if x["display_name"].startswith("Ravi"))
    assert (ravi["bill_count"], ravi["days_31_60"], ravi["not_due"], ravi["total"]) == (
        2,
        "50000.00",
        "58500.00",
        "108500.00",
    )
    assert report["totals"]["total"] == "167000.00"  # 108500 + the firm's bill, 58500
    assert report["results"][0]["display_name"].startswith("Ravi")  # biggest first


def test_who_may_do_what(b: Books) -> None:
    engineer, viewer = add_member(b.t, "SITE_ENGINEER"), add_member(b.t, "VIEWER")
    assert b.bill(engineer).status_code == 403
    assert b.get("/api/v1/vendor-bills", engineer).status_code == 200
    assert b.get("/api/v1/reports/payables", engineer).status_code == 403
    assert b.get("/api/v1/reports/payables", viewer).status_code == 200


def test_another_business_reaches_none_of_it(b: Books) -> None:
    bill = b.bill().json()
    payment = b.pay("1000.00", [{"vendor_bill_id": bill["id"], "amount": "1000.00"}]).json()
    other = Books("Other Builders")
    for url in (f"/api/v1/vendor-bills/{bill['id']}", f"/api/v1/vendor-payments/{payment['id']}"):
        assert other.get(url).status_code == 404
    void = APIClient().post(
        f"/api/v1/vendor-bills/{bill['id']}/void",
        {"reason": "hijack"},
        format="json",
        **other.h(IF_MATCH='"v1"'),
    )
    assert void.status_code == 404
    void = APIClient().post(
        f"/api/v1/vendor-payments/{payment['id']}/void",
        {"reason": "hijack"},
        format="json",
        **other.h(IF_MATCH='"v1"'),
    )
    assert void.status_code == 404
    assert other.get("/api/v1/vendor-bills").json()["results"] == []
    assert other.get("/api/v1/vendor-payments").json()["results"] == []
    assert other.get("/api/v1/reports/payables").json()["results"] == []
    hint = other.get(
        "/api/v1/vendor-bills/tds-suggestion",
        vendor_party_id=str(b.vendor.pk),
        category="SUBCONTRACT",
        taxable_value="50000.00",
        bill_date="2026-10-10",
    )
    assert err(hint) == (422, "not_found")
    stolen = other.pay(
        "1000.00",
        [{"vendor_bill_id": bill["id"], "amount": "1000.00"}],
        vendor_party_id=str(other.vendor.pk),
    )
    assert err(stolen) == (422, "not_found")
    assert b.get(f"/api/v1/vendor-bills/{bill['id']}").json()["amount_paid"] == "1000.00"
