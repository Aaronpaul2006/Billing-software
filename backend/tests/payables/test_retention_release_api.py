"""Retention released to subcontractors, through the API (payables part 2, step 4).

RA bill 1 (see test_work_orders_api.py) holds 11000 of retention.
"""

from decimal import Decimal
from typing import Any

import pytest

from tests.factories import add_member
from tests.payables.test_work_orders_api import Site, err

pytestmark = pytest.mark.django_db


@pytest.fixture
def s() -> tuple[Site, dict[str, Any], dict[str, Any]]:
    site = Site()
    wo = site.work_order().json()
    bill = site.ra_bill(wo, ["40", "200"]).json()
    return site, wo, bill


def release(site: Site, wo: dict[str, Any], amount: str, **body: Any) -> Any:
    return site.call(
        "post",
        f"work-orders/{wo['id']}/retention-releases",
        {"release_date": "2026-11-05", "amount": amount, **body},
    )


def test_release_and_pay_it_with_a_bill(s: tuple[Site, Any, Any]) -> None:
    site, wo, bill = s
    assert err(release(site, wo, "11000.01")) == (422, "exceeds_retention_held")
    r = release(site, wo, "6000.00", due_date="2026-11-20", reference="RET-1")
    assert r.status_code == 201, r.content
    rel = r.json()
    assert (rel["wo_number"], rel["outstanding"], rel["status"]) == (
        "WO/VILLA-1/01",
        "6000.00",
        "RELEASED",
    )
    detail = site.call("get", f"work-orders/{wo['id']}").json()
    assert (detail["retention_held"], detail["retention_released"]) == ("11000.00", "6000.00")
    assert detail["retention_to_release"] == "5000.00"
    assert [x["amount"] for x in detail["releases"]] == ["6000.00"]
    owed = site.call("get", "reports/payables").json()["totals"]
    assert (owed["total"], owed["bill_count"]) == ("252400.00", 2)  # 246400 + 6000
    flow = site.call("get", "reports/cash-flow?weeks=13").json()
    out = [b for w in flow["weeks"] for b in w["bills_out"] if b["kind"] == "RETENTION_OUT"]
    # due 20 Nov 2026: in a week of the forecast, or overdue when the tests run later
    assert [b["number"] for b in out] == ["Retention, WO/VILLA-1/01"] or Decimal(
        flow["overdue_out"]
    ) >= Decimal("6000.00")
    open_ = site.call(
        "get", f"vendor-retention-releases?open=true&vendor_party_id={site.vendor.pk}"
    )
    assert [x["id"] for x in open_.json()["results"]] == [rel["id"]]

    paid = site.pay(
        "252400.00",
        [
            {"vendor_bill_id": bill["id"], "amount": "246400.00"},
            {"vendor_retention_release_id": rel["id"], "amount": "6000.00"},
        ],
    )
    assert paid.status_code == 201, paid.content
    labels = [a["bill_number"] for a in paid.json()["allocations"]]
    assert "Retention, WO/VILLA-1/01" in labels
    assert site.call("get", "vendor-retention-releases?open=true").json()["results"] == []
    assert site.call("get", "reports/payables").json()["totals"]["total"] == "0.00"
    r = site.call(
        "post",
        f"vendor-retention-releases/{rel['id']}/cancel",
        {"reason": "not due yet"},
        IF_MATCH='"v1"',
    )
    assert err(r) == (409, "release_paid")


def test_cancel_frees_it_and_a_released_bill_is_not_voided(s: tuple[Site, Any, Any]) -> None:
    site, wo, bill = s
    rel = release(site, wo, "11000.00").json()
    r = site.call(
        "post", f"vendor-bills/{bill['id']}/void", {"reason": "not due yet"}, IF_MATCH='"v1"'
    )
    assert err(r) == (409, "retention_released")
    r = site.call(
        "post",
        f"vendor-retention-releases/{rel['id']}/cancel",
        {"reason": "early"},
        IF_MATCH='"v1"',
    )
    assert r.json()["status"] == "CANCELLED"
    assert release(site, wo, "11000.00").status_code == 201


def test_checks(s: tuple[Site, Any, Any]) -> None:
    site, wo, bill = s
    assert err(release(site, wo, "100.00", due_date="2026-11-01")) == (422, "invalid")
    r = site.pay("100.00", [{"amount": "100.00"}])  # neither a bill nor a release
    assert r.status_code == 422
    rel = release(site, wo, "100.00").json()
    r = site.pay(
        "200.00",
        [{"vendor_bill_id": bill["id"], "vendor_retention_release_id": rel["id"], "amount": "1"}],
    )
    assert r.status_code == 422  # both at once


def test_who_may(s: tuple[Site, Any, Any]) -> None:
    site, wo, _ = s
    viewer = add_member(site.t, "VIEWER")
    assert site.get("/api/v1/vendor-retention-releases", viewer).status_code == 200
    r = site.call(
        "post",
        f"work-orders/{wo['id']}/retention-releases",
        {},
    )
    assert r.status_code == 422  # the owner may; the body is empty


def test_another_business_reaches_none_of_it(s: tuple[Site, Any, Any]) -> None:
    site, wo, _ = s
    rel = release(site, wo, "100.00").json()
    other = Site("Other Builders")
    assert other.call("get", "vendor-retention-releases").json()["results"] == []
    assert release(other, wo, "1.00").status_code == 404
    r = other.call(
        "post",
        f"vendor-retention-releases/{rel['id']}/cancel",
        {"reason": "not due yet"},
        IF_MATCH='"v1"',
    )
    assert r.status_code == 404
