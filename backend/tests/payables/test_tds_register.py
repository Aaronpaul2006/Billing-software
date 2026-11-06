"""The register of TDS we deducted on vendor bills (payables step 4): one row per
bill with TDS, by month, with a total; voided bills and bills without TDS left out."""

import uuid
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.exports.builders import tds_deducted
from tests.payables.test_api import Books

pytestmark = pytest.mark.django_db


def test_one_row_per_bill_with_tds_and_a_total() -> None:
    b = Books()
    b.bill(bill_number="RK/1", bill_date="2026-10-10", due_date=None)  # 194C 1 %: 500
    b.bill(
        vendor_party_id=str(b.firm.pk),
        bill_number="KS/9",
        bill_date="2026-11-02",
        due_date=None,
        tds_rate="2.00",
    )  # 1000
    b.bill(
        bill_number="RK/2", bill_date="2026-10-12", due_date=None, tds_section=None, tds_rate=None
    )  # no TDS: not listed
    voided = b.bill(bill_number="RK/3", bill_date="2026-10-15", due_date=None).json()
    r = APIClient().post(
        f"/api/v1/vendor-bills/{voided['id']}/void",
        {"reason": "twice"},
        format="json",
        **b.h(IF_MATCH='"v1"'),
    )
    assert r.status_code == 200, r.content
    with tenant_context(b.t.tenant_id, b.t.user_id):
        built = tds_deducted(b.t.tenant_id, {"from": "2026-04-01", "to": "2027-03-31"})
    rows = built.table.rows
    assert [(r[0], r[2], r[3], r[4], r[5], r[8]) for r in rows[:-1]] == [
        (
            "Oct 2026",
            "Ravi Kumar (labour contractor)",
            "ABCPK1234L",
            "194C",
            "RK/1",
            Decimal("500.00"),
        ),
        ("Nov 2026", "Kerala Steel Traders", "AAACK1234M", "194C", "KS/9", Decimal("1000.00")),
    ]
    assert (rows[-1][2], rows[-1][6], rows[-1][8]) == (
        "Total",
        Decimal("100000.00"),
        Decimal("1500.00"),
    )
    assert built.stem == "tds_deducted_2026-04-01_2027-03-31"


def test_it_can_be_asked_for_like_the_other_registers() -> None:
    b = Books()
    r = APIClient().post(
        "/api/v1/exports",
        {
            "kind": "TDS_DEDUCTED",
            "format": "XLSX",
            "params": {"from": "2026-04-01", "to": "2026-10-31"},
        },
        format="json",
        **b.h(IDEMPOTENCY_KEY=str(uuid.uuid4())),
    )
    assert r.status_code in (201, 202), r.content
    assert r.json()["kind"] == "TDS_DEDUCTED"
