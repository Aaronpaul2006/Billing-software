"""Payables rules the database itself enforces (Part B, db/schema.sql 7d):
what was paid on a vendor bill moves only with its allocations, never past what
we owe, and only from a recorded payment to the same vendor."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.db import DatabaseError, connection, transaction

from apps.core.tenancy import tenant_context
from apps.parties.models import Party
from apps.payables.models import VendorAllocation, VendorBill, VendorPayment
from tests.factories import TenantFixture, make_tenant

pytestmark = pytest.mark.django_db


def vendor(t: TenantFixture, name: str) -> Party:
    party: Party = Party.objects.create(
        display_name=name,
        gst_treatment="UNREGISTERED",
        is_customer=False,
        is_vendor=True,
        created_by_id=t.user_id,
    )
    return party


def bill(t: TenantFixture, v: Party, **kw: Any) -> VendorBill:
    # 50000 + 18 % GST = 59000; TDS 1 % on the value before GST = 500; we owe 58500
    fields: dict[str, Any] = {
        "vendor_party": v,
        "bill_number": "KST/101",
        "bill_date": date(2026, 10, 10),
        "category": "MATERIAL",
        "description": "TMT steel",
        "taxable_value": Decimal("50000.00"),
        "gst_amount": Decimal("9000.00"),
        "total_amount": Decimal("59000.00"),
        "tds_section": "194C",
        "tds_rate": Decimal("1.00"),
        "tds_amount": Decimal("500.00"),
        "net_payable": Decimal("58500.00"),
        "created_by_id": t.user_id,
        **kw,
    }
    created: VendorBill = VendorBill.objects.create(**fields)
    return created


def payment(t: TenantFixture, v: Party, amount: str) -> VendorPayment:
    created: VendorPayment = VendorPayment.objects.create(
        vendor_party=v,
        payment_date=date(2026, 10, 20),
        amount=Decimal(amount),
        mode="BANK_TRANSFER",
        created_by_id=t.user_id,
    )
    return created


def allocate(t: TenantFixture, p: VendorPayment, b: VendorBill, amount: str) -> None:
    VendorAllocation.objects.create(
        vendor_payment=p, vendor_bill=b, amount=Decimal(amount), created_by_id=t.user_id
    )


def paid(b: VendorBill) -> Decimal:
    value: Decimal = VendorBill.objects.get(pk=b.pk).amount_paid
    return value


def test_amount_paid_follows_allocations_and_never_passes_what_we_owe() -> None:
    t = make_tenant()
    with tenant_context(t.tenant_id, t.user_id):
        v = vendor(t, "Kerala Steel Traders")
        b = bill(t, v)
        p1 = payment(t, v, "50000.00")
        allocate(t, p1, b, "50000.00")
        assert paid(b) == Decimal("50000.00")
        p2 = payment(t, v, "10000.00")
        with pytest.raises(DatabaseError), transaction.atomic():
            allocate(t, p2, b, "10000.00")  # 60000 > 58500 owed
        allocate(t, p2, b, "8500.00")
        assert paid(b) == Decimal("58500.00")
        VendorAllocation.objects.filter(vendor_payment=p2).delete()
        assert paid(b) == Decimal("50000.00")


def test_only_a_recorded_payment_to_the_same_vendor_pays_a_bill() -> None:
    t = make_tenant()
    with tenant_context(t.tenant_id, t.user_id):
        v, other = vendor(t, "Kerala Steel Traders"), vendor(t, "Coastal Cement")
        b = bill(t, v)
        with pytest.raises(DatabaseError), transaction.atomic():
            allocate(t, payment(t, other, "1000.00"), b, "1000.00")
        p = payment(t, v, "1000.00")
        with pytest.raises(DatabaseError), transaction.atomic():
            allocate(t, p, b, "1000.01")  # more than the payment
        allocate(t, p, b, "1000.00")
        a = VendorAllocation.objects.get(vendor_payment=p)
        with pytest.raises(DatabaseError), transaction.atomic():
            VendorAllocation.objects.filter(pk=a.pk).update(amount=Decimal("1.00"))


def test_the_app_cannot_set_what_was_paid_directly() -> None:
    t = make_tenant()
    with tenant_context(t.tenant_id, t.user_id):
        b = bill(t, vendor(t, "Kerala Steel Traders"))
        with pytest.raises(DatabaseError), transaction.atomic():
            VendorBill.objects.filter(pk=b.pk).update(amount_paid=Decimal("1.00"))


def test_sums_must_add_up() -> None:
    t = make_tenant()
    with tenant_context(t.tenant_id, t.user_id):
        v = vendor(t, "Kerala Steel Traders")
        with pytest.raises(DatabaseError), transaction.atomic():
            bill(t, v, net_payable=Decimal("59000.00"))  # TDS not taken off
        with pytest.raises(DatabaseError), transaction.atomic():
            bill(t, v, tds_section=None)  # TDS without a section
        bill(t, v)
        with pytest.raises(DatabaseError), transaction.atomic():
            bill(t, v, bill_number="kst/101")  # the same vendor bill twice


def test_another_business_sees_none_of_it() -> None:
    a, b_ = make_tenant(), make_tenant("Other Builders")
    with tenant_context(a.tenant_id, a.user_id):
        bill(a, vendor(a, "Kerala Steel Traders"))
    with tenant_context(b_.tenant_id, b_.user_id):
        assert VendorBill.objects.count() == 0
        with connection.cursor() as cur:
            cur.execute("SELECT count(*) FROM vendor_bills")
            assert cur.fetchone() == (0,)
