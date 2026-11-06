"""Retention released to subcontractors: the database's rules (payables part 2,
step 4; db/schema.sql 7d and 7e). RA bill 1 holds 8000 (5 % of 160000)."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.db import DatabaseError, transaction

from apps.core.tenancy import tenant_context
from apps.payables.models import (
    VendorAllocation,
    VendorBill,
    VendorPayment,
    VendorRetentionRelease,
)
from tests.factories import make_tenant
from tests.payables.test_work_order_db import Site

pytestmark = pytest.mark.django_db


@pytest.fixture
def site() -> Any:
    t = make_tenant()
    with tenant_context(t.tenant_id, t.user_id):
        s = Site(t)
        s.line(s.ra_bill(1), s.brick, "40")
        yield s


def release(site: Site, amount: str, **kw: Any) -> VendorRetentionRelease:
    fields: dict[str, Any] = {
        "work_order": site.wo,
        "vendor_party": site.sub,
        "release_date": date(2026, 11, 1),
        "amount": Decimal(amount),
        "created_by_id": site.t.user_id,
        **kw,
    }
    created: VendorRetentionRelease = VendorRetentionRelease.objects.create(**fields)
    return created


def pay(site: Site, amount: str) -> VendorPayment:
    created: VendorPayment = VendorPayment.objects.create(
        vendor_party=site.sub,
        payment_date=date(2026, 11, 5),
        amount=Decimal(amount),
        mode="BANK_TRANSFER",
        created_by_id=site.t.user_id,
    )
    return created


def test_never_more_than_is_held(site: Site) -> None:
    release(site, "5000.00")
    with pytest.raises(DatabaseError), transaction.atomic():
        release(site, "3000.01")  # 8000.01 > 8000 held
    r = release(site, "3000.00")
    with pytest.raises(DatabaseError), transaction.atomic():
        VendorRetentionRelease.objects.filter(pk=r.pk).update(amount=Decimal("1.00"))
    # a cancelled release frees what it took
    VendorRetentionRelease.objects.filter(pk=r.pk).update(
        status="CANCELLED", cancelled_at="2026-11-02T10:00:00+05:30", cancel_reason="early"
    )
    release(site, "3000.00")


def test_only_to_the_work_orders_subcontractor(site: Site) -> None:
    with pytest.raises(DatabaseError), transaction.atomic():
        release(site, "100.00", vendor_party=site.vendor("Somebody else"))


def test_an_ra_bill_whose_retention_is_released_stays(site: Site) -> None:
    release(site, "8000.00")
    bill = VendorBill.objects.get(ra_number=1)
    with pytest.raises(DatabaseError), transaction.atomic():
        VendorBill.objects.filter(pk=bill.pk).update(
            status="VOIDED", voided_at="2026-11-02T10:00:00+05:30", void_reason="x"
        )


def test_a_release_is_paid_like_a_bill(site: Site) -> None:
    r = release(site, "8000.00")
    p = pay(site, "10000.00")
    VendorAllocation.objects.create(
        vendor_payment=p,
        vendor_retention_release=r,
        amount=Decimal("8000.00"),
        created_by_id=site.t.user_id,
    )
    assert VendorRetentionRelease.objects.get(pk=r.pk).amount_paid == Decimal("8000.00")
    with pytest.raises(DatabaseError), transaction.atomic():
        VendorAllocation.objects.create(  # paid twice over
            vendor_payment=pay(site, "1.00"),
            vendor_retention_release=r,
            amount=Decimal("1.00"),
            created_by_id=site.t.user_id,
        )
    with pytest.raises(DatabaseError), transaction.atomic():
        VendorAllocation.objects.create(  # a bill and a release at once
            vendor_payment=p,
            vendor_retention_release=r,
            vendor_bill=VendorBill.objects.get(ra_number=1),
            amount=Decimal("1.00"),
            created_by_id=site.t.user_id,
        )
    with pytest.raises(DatabaseError), transaction.atomic():  # paid: not cancelled
        VendorRetentionRelease.objects.filter(pk=r.pk).update(
            status="CANCELLED", cancelled_at="2026-11-06T10:00:00+05:30", cancel_reason="x"
        )
    VendorAllocation.objects.filter(vendor_retention_release=r).delete()
    assert VendorRetentionRelease.objects.get(pk=r.pk).amount_paid == Decimal("0.00")


def test_the_app_cannot_set_what_was_paid(site: Site) -> None:
    r = release(site, "100.00")
    with pytest.raises(DatabaseError), transaction.atomic():
        VendorRetentionRelease.objects.filter(pk=r.pk).update(amount_paid=Decimal("1.00"))
