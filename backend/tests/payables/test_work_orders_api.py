"""Subcontract work orders and RA bills received, through the API (payables part 2).

Brickwork 100 cum at 4,000 (linked to the client's BOQ item 2.1) and
plastering 500 sqm at 300; retention 5 %, TDS 194C 1 %. RA bill 1: 40 cum of
brickwork and 200 sqm of plastering = 160000 + 60000 = 220000; GST 18 % =
39600; TDS 1 % = 2200; retention 5 % = 11000; we owe 246400.
"""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.projects.models import BoqItem
from tests.factories import add_member
from tests.payables.test_api import Books

pytestmark = pytest.mark.django_db


class Site(Books):
    def __init__(self, name: str = "Nair Constructions") -> None:
        super().__init__(name)
        with tenant_context(self.t.tenant_id, self.t.user_id):
            self.boq = BoqItem.objects.create(
                project=self.project,
                item_code="2.1",
                description="Brick masonry in CM 1:6",
                unit="cum",
                contract_qty=Decimal("120"),
                rate=Decimal("6200"),
            )

    def call(self, method: str, url: str, body: Any = None, **headers: str) -> Any:
        h = self.h(None, IDEMPOTENCY_KEY=str(uuid.uuid4()), **headers)
        return getattr(APIClient(), method)(f"/api/v1/{url}", body, format="json", **h)

    def work_order(self, **body: Any) -> Any:
        return self.call(
            "post",
            "work-orders",
            {
                "project_id": str(self.project.pk),
                "vendor_party_id": str(self.vendor.pk),
                "wo_date": "2026-10-01",
                "title": "Brickwork and plastering, ground floor",
                "retention_pct": "5",
                "tds_section": "194C",
                "tds_rate": "1",
                "items": [
                    {
                        "boq_item_id": str(self.boq.pk),
                        "item_code": "1",
                        "description": "Brickwork in CM 1:6",
                        "unit": "cum",
                        "qty": "100",
                        "rate": "4000",
                    },
                    {
                        "item_code": "2",
                        "description": "Plastering 12 mm",
                        "unit": "sqm",
                        "qty": "500",
                        "rate": "300",
                    },
                ],
                **body,
            },
        )

    def ra_bill(self, wo: dict[str, Any], quantities: list[str], **body: Any) -> Any:
        lines = [
            {"work_order_item_id": item["id"], "qty": q}
            for item, q in zip(wo["items"], quantities, strict=False)
            if q
        ]
        return self.call(
            "post",
            f"work-orders/{wo['id']}/ra-bills",
            {
                "bill_number": f"RK/RA/{uuid.uuid4().hex[:4]}",
                "bill_date": "2026-10-25",
                "lines": lines,
                **body,
            },
        )


@pytest.fixture
def s() -> Site:
    return Site()


def err(r: Any) -> tuple[int, str]:
    body = r.json()
    code = body["errors"][0]["code"] if body["code"] == "validation_error" else body["code"]
    return r.status_code, code


def test_a_work_order_and_its_first_ra_bill(s: Site) -> None:
    r = s.work_order()
    assert r.status_code == 201, r.content
    wo = r.json()
    assert wo["wo_number"] == "WO/VILLA-1/01"
    assert (wo["value"], wo["billed"], wo["ra_count"], wo["status"]) == (
        "550000.00",
        "0.00",
        0,
        "OPEN",
    )
    brick = wo["items"][0]
    assert (brick["boq_item_code"], brick["amount"], brick["balance_qty"]) == (
        "2.1",
        "400000.00",
        "100.000",
    )

    r = s.ra_bill(wo, ["40", "200"], due_date="2026-11-10")
    assert r.status_code == 201, r.content
    bill = r.json()
    assert (bill["ra_number"], bill["wo_number"], bill["category"]) == (
        1,
        "WO/VILLA-1/01",
        "SUBCONTRACT",
    )
    assert (bill["taxable_value"], bill["gst_amount"], bill["tds_amount"]) == (
        "220000.00",
        "39600.00",
        "2200.00",
    )
    assert (bill["retention_amount"], bill["net_payable"]) == ("11000.00", "246400.00")
    assert [(x["item_code"], x["qty"], x["amount"]) for x in bill["lines"]] == [
        ("1", "40.000", "160000.00"),
        ("2", "200.000", "60000.00"),
    ]
    assert bill["description"].startswith("RA bill 1 · Brickwork")

    wo = s.call("get", f"work-orders/{wo['id']}").json()
    assert (wo["billed"], wo["retention_held"], wo["ra_count"]) == ("220000.00", "11000.00", 1)
    assert [(i["billed_qty"], i["balance_qty"]) for i in wo["items"]] == [
        ("40.000", "60.000"),
        ("200.000", "300.000"),
    ]
    assert [b["ra_number"] for b in wo["ra_bills"]] == [1]
    detail = s.call("get", f"vendor-bills/{bill['id']}").json()
    assert len(detail["lines"]) == 2
    # the payables report counts what we owe after retention
    owed = s.call("get", "reports/payables").json()["totals"]["total"]
    assert owed == "246400.00"


def test_bills_stay_within_the_work_order(s: Site) -> None:
    wo = s.work_order().json()
    assert s.ra_bill(wo, ["40"]).status_code == 201
    r = s.ra_bill(wo, ["60.5"])
    assert err(r) == (422, "exceeds_work_order")
    assert "Only 60 cum of item 1 is left" in r.json()["errors"][0]["message"]
    second = s.ra_bill(wo, ["60"]).json()
    assert second["ra_number"] == 2
    assert err(s.ra_bill(wo, ["", "10"], ra_number=1)) == (422, "duplicate")
    other = s.work_order(title="Another").json()
    r = s.call(
        "post",
        f"work-orders/{wo['id']}/ra-bills",
        {
            "bill_number": "X/1",
            "bill_date": "2026-10-25",
            "lines": [{"work_order_item_id": other["items"][0]["id"], "qty": "1"}],
        },
    )
    assert err(r) == (422, "not_found")
    assert err(s.ra_bill(wo, [])) == (422, "required")


def test_amend_the_work_order_to_bill_more(s: Site) -> None:
    wo = s.work_order().json()
    s.ra_bill(wo, ["100"])
    items = [
        {k: i[k] for k in ("id", "item_code", "description", "unit", "rate")} for i in wo["items"]
    ]
    items[0]["qty"], items[1]["qty"] = "99", "500"
    r = s.call("patch", f"work-orders/{wo['id']}", {"items": items}, IF_MATCH='"v1"')
    assert err(r) == (422, "below_billed")
    items[0]["qty"] = "110"
    r = s.call("patch", f"work-orders/{wo['id']}", {"items": items[:1]}, IF_MATCH='"v1"')
    assert r.status_code == 200, r.content  # plastering removed: nothing billed on it
    assert [i["item_code"] for i in r.json()["items"]] == ["1"]
    assert s.ra_bill(r.json(), ["10"]).status_code == 201
    r = s.call("patch", f"work-orders/{wo['id']}", {"items": []}, IF_MATCH='"v2"')
    assert err(r) == (422, "required")


def test_close_reopen_and_void(s: Site) -> None:
    wo = s.work_order().json()
    bill = s.ra_bill(wo, ["40"]).json()
    r = s.call("post", f"work-orders/{wo['id']}/close", IF_MATCH='"v1"')
    assert r.json()["status"] == "CLOSED"
    assert err(s.ra_bill(wo, ["10"])) == (409, "work_order_closed")
    s.call("post", f"work-orders/{wo['id']}/reopen", IF_MATCH='"v2"')
    # an RA bill is not edited; voiding it frees its quantity
    r = s.call("patch", f"vendor-bills/{bill['id']}", {"notes": "x"}, IF_MATCH='"v1"')
    assert err(r) == (409, "ra_bill_edit")
    r = s.call("post", f"vendor-bills/{bill['id']}/void", {"reason": "wrong"}, IF_MATCH='"v1"')
    assert r.status_code == 200, r.content
    again = s.ra_bill(wo, ["100"]).json()
    assert again["ra_number"] == 1  # the voided number is free again


def test_checks_on_the_work_order(s: Site) -> None:
    assert err(s.work_order(vendor_party_id=str(s.client.pk))) == (422, "not_a_vendor")
    assert err(s.work_order(items=[])) == (422, "required")
    s.work_order(wo_number="WO-7")
    assert err(s.work_order(wo_number="wo-7")) == (422, "duplicate")
    assert err(s.work_order(tds_section=None)) == (422, "required")  # a rate without a section


def test_who_may_do_what(s: Site) -> None:
    wo = s.work_order().json()
    engineer, viewer = add_member(s.t, "SITE_ENGINEER"), add_member(s.t, "VIEWER")
    assert s.get("/api/v1/work-orders", viewer).status_code == 200
    r = APIClient().post(
        "/api/v1/work-orders", {}, format="json", **s.h(engineer, IDEMPOTENCY_KEY="k1")
    )
    assert r.status_code == 403
    assert s.get(f"/api/v1/work-orders/{wo['id']}", viewer).status_code == 200


def test_another_business_reaches_none_of_it(s: Site) -> None:
    wo = s.work_order().json()
    other = Site("Other Builders")
    assert other.call("get", f"work-orders/{wo['id']}").status_code == 404
    assert other.call("get", "work-orders").json()["results"] == []
    for action in ("close", "reopen"):
        r = other.call("post", f"work-orders/{wo['id']}/{action}", IF_MATCH='"v1"')
        assert r.status_code == 404
    r = other.call("patch", f"work-orders/{wo['id']}", {"title": "x"}, IF_MATCH='"v1"')
    assert r.status_code == 404
    assert other.ra_bill(wo, ["1"]).status_code == 404
