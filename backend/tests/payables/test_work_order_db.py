"""Subcontract RA bill rules the database enforces (payables part 2, 7e).

The work order: brickwork, 100 cum at 4,000 and plastering, 500 sqm at 300,
retention 5 %. An RA bill for 40 cum of brickwork is 160000; TDS 1 % = 1600,
retention 5 % = 8000, GST 18 % = 28800, so we owe 179200.
"""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.db import DatabaseError, connection, transaction

from apps.core.tenancy import tenant_context
from apps.parties.models import Party
from apps.payables.models import (
    VendorAllocation,
    VendorBill,
    VendorBillLine,
    VendorPayment,
    WorkOrder,
    WorkOrderItem,
)
from apps.projects.models import Project
from tests.factories import TenantFixture, make_tenant

pytestmark = pytest.mark.django_db


class Site:
    def __init__(self, t: TenantFixture) -> None:
        self.t = t
        client = Party.objects.create(
            display_name="Skyline Developers", gst_treatment="UNREGISTERED", created_by_id=t.user_id
        )
        self.project = Project.objects.create(
            code="VILLA-1",
            name="Villa",
            client_party=client,
            gst_registration_id=t.registration_id,
            site_state_code="32",
            created_by_id=t.user_id,
        )
        self.sub = self.vendor("Ravi Kumar (brickwork)")
        self.wo = WorkOrder.objects.create(
            project=self.project,
            vendor_party=self.sub,
            wo_number="WO/1",
            wo_date=date(2026, 10, 1),
            title="Brickwork and plastering",
            retention_pct=Decimal("5"),
            tds_section="194C",
            tds_rate=Decimal("1"),
            created_by_id=t.user_id,
        )
        self.brick = self.item("1", "Brickwork in CM 1:6", "cum", "100", "4000")
        self.plaster = self.item("2", "Plastering 12 mm", "sqm", "500", "300")

    def vendor(self, name: str) -> Party:
        party: Party = Party.objects.create(
            display_name=name,
            gst_treatment="UNREGISTERED",
            is_customer=False,
            is_vendor=True,
            created_by_id=self.t.user_id,
        )
        return party

    def item(self, code: str, what: str, unit: str, qty: str, rate: str) -> WorkOrderItem:
        created: WorkOrderItem = WorkOrderItem.objects.create(
            work_order=self.wo,
            item_code=code,
            description=what,
            unit=unit,
            qty=Decimal(qty),
            rate=Decimal(rate),
        )
        return created

    def ra_bill(self, number: int, qty: str = "40", **kw: Any) -> VendorBill:
        value = Decimal(qty) * Decimal("4000")
        gst, tds, retention = value * Decimal("0.18"), value / 100, value / 20
        fields: dict[str, Any] = {
            "vendor_party": self.sub,
            "project": self.project,
            "work_order": self.wo,
            "ra_number": number,
            "bill_number": f"RK/RA-{number}",
            "bill_date": date(2026, 10, 20),
            "category": "SUBCONTRACT",
            "description": f"RA bill {number}",
            "taxable_value": value,
            "gst_amount": gst,
            "total_amount": value + gst,
            "tds_section": "194C",
            "tds_rate": Decimal("1"),
            "tds_amount": tds,
            "retention_amount": retention,
            "net_payable": value + gst - tds - retention,
            "created_by_id": self.t.user_id,
            **kw,
        }
        b: VendorBill = VendorBill.objects.create(**fields)
        return b

    def line(self, b: VendorBill, item: WorkOrderItem, qty: str) -> VendorBillLine:
        q = Decimal(qty)
        created: VendorBillLine = VendorBillLine.objects.create(
            vendor_bill=b,
            work_order_item=item,
            qty=q,
            rate=item.rate,
            amount=(q * item.rate).quantize(Decimal("0.01")),
            gst_rate=item.gst_rate,
        )
        return created


@pytest.fixture
def site() -> Any:
    t = make_tenant()
    with tenant_context(t.tenant_id, t.user_id):
        yield Site(t)


def test_ra_bills_never_pass_the_agreed_quantity(site: Site) -> None:
    first = site.ra_bill(1)
    assert first.net_payable == Decimal("179200.00")
    site.line(first, site.brick, "40")
    second = site.ra_bill(2, qty="60")
    with pytest.raises(DatabaseError), transaction.atomic():
        site.line(second, site.brick, "60.001")  # 100.001 > 100 cum
    site.line(second, site.brick, "60")
    # a voided bill no longer counts: its 40 cum can be billed again
    VendorBill.objects.filter(pk=first.pk).update(
        status="VOIDED", voided_at="2026-10-21T10:00:00+05:30", void_reason="wrong measurement"
    )
    third = site.ra_bill(3)
    site.line(third, site.brick, "40")


def test_an_item_cannot_be_cut_below_what_is_billed(site: Site) -> None:
    site.line(site.ra_bill(1), site.brick, "40")
    with pytest.raises(DatabaseError), transaction.atomic():
        WorkOrderItem.objects.filter(pk=site.brick.pk).update(qty=Decimal("39.999"))
    WorkOrderItem.objects.filter(pk=site.brick.pk).update(qty=Decimal("40"))
    WorkOrderItem.objects.filter(pk=site.brick.pk).update(qty=Decimal("120"))  # amended up
    with pytest.raises(DatabaseError), transaction.atomic():
        site.brick.delete()  # billed: it stays
    site.plaster.delete()  # never billed: may go


def test_lines_belong_to_the_bills_work_order(site: Site) -> None:
    other = WorkOrder.objects.create(
        project=site.project,
        vendor_party=site.sub,
        wo_number="WO/2",
        wo_date=date(2026, 10, 1),
        title="Flooring",
        created_by_id=site.t.user_id,
    )
    tiles = WorkOrderItem.objects.create(
        work_order=other,
        item_code="1",
        description="Vitrified tiles",
        unit="sqm",
        qty=Decimal("200"),
        rate=Decimal("4000"),
    )
    b = site.ra_bill(1)
    with pytest.raises(DatabaseError), transaction.atomic():
        site.line(b, tiles, "40")
    line = site.line(b, site.brick, "40")
    with pytest.raises(DatabaseError), transaction.atomic():
        VendorBillLine.objects.filter(pk=line.pk).update(qty=Decimal("30"))  # no updates
    with pytest.raises(DatabaseError), transaction.atomic():
        VendorBillLine.objects.create(  # the amount is qty x rate
            vendor_bill=b,
            work_order_item=site.plaster,
            qty=Decimal("10"),
            rate=Decimal("300"),
            amount=Decimal("3001.00"),
            gst_rate=Decimal("18"),
        )


def test_an_ra_bill_is_the_subcontractors_for_the_project_while_open(site: Site) -> None:
    stranger = site.vendor("Somebody else")
    with pytest.raises(DatabaseError), transaction.atomic():
        site.ra_bill(1, vendor_party=stranger)
    with pytest.raises(DatabaseError), transaction.atomic():
        site.ra_bill(1, project=None)
    with pytest.raises(DatabaseError), transaction.atomic():
        site.ra_bill(1, ra_number=None)  # a work order bill has its RA number
    site.ra_bill(1)
    with pytest.raises(DatabaseError), transaction.atomic():
        site.ra_bill(1, bill_number="RK/RA-1b")  # RA 1 twice
    WorkOrder.objects.filter(pk=site.wo.pk).update(status="CLOSED")
    with pytest.raises(DatabaseError), transaction.atomic():
        site.ra_bill(2)


def test_retention_is_for_ra_bills_and_comes_off_what_we_owe(site: Site) -> None:
    plain: dict[str, Any] = {"work_order": None, "ra_number": None}
    with pytest.raises(DatabaseError), transaction.atomic():
        site.ra_bill(1, **plain)  # retention without a work order
    with pytest.raises(DatabaseError), transaction.atomic():
        site.ra_bill(1, net_payable=Decimal("187200.00"))  # retention not taken off
    b = site.ra_bill(1)
    with pytest.raises(DatabaseError), transaction.atomic():
        VendorBill.objects.filter(pk=b.pk).update(ra_number=5)


def test_lines_of_a_paid_bill_stay(site: Site) -> None:
    b = site.ra_bill(1)
    line = site.line(b, site.brick, "40")
    p = VendorPayment.objects.create(
        vendor_party=site.sub,
        payment_date=date(2026, 10, 25),
        amount=Decimal("1000.00"),
        mode="BANK_TRANSFER",
        created_by_id=site.t.user_id,
    )
    VendorAllocation.objects.create(
        vendor_payment=p, vendor_bill=b, amount=Decimal("1000.00"), created_by_id=site.t.user_id
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        VendorBillLine.objects.filter(pk=line.pk).delete()


def test_another_business_sees_none_of_it() -> None:
    t = make_tenant()
    with tenant_context(t.tenant_id, t.user_id):
        site = Site(t)
        site.line(site.ra_bill(1), site.brick, "40")
    other = make_tenant("Other Builders")
    with tenant_context(other.tenant_id, other.user_id), connection.cursor() as cur:
        for table in ("work_orders", "work_order_items", "vendor_bill_lines"):
            cur.execute(f"SELECT count(*) FROM {table}")  # noqa: S608
            assert cur.fetchone() == (0,), table
