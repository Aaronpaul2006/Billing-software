"""GSTR-2B tables (Part B): one per registration and month, never edited,
replaced whole; another business sees none of it."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.db import DatabaseError, connection, transaction

from apps.core.tenancy import tenant_context
from apps.gstr2b.models import Gstr2bLine, Gstr2bReturn
from tests.factories import TenantFixture, make_tenant

pytestmark = pytest.mark.django_db


def upload(t: TenantFixture, **kw: Any) -> Gstr2bReturn:
    r: Gstr2bReturn = Gstr2bReturn.objects.create(
        gst_registration_id=t.registration_id,
        period=kw.pop("period", date(2026, 10, 1)),
        file_name="returns_102026_R2B.json",
        doc_count=1,
        created_by_id=t.user_id,
        **kw,
    )
    Gstr2bLine.objects.create(
        gst_return=r,
        section="B2B",
        doc_type="INVOICE",
        supplier_gstin="32AAACK1234M1Z8",
        doc_number="KST/101",
        doc_date=date(2026, 10, 10),
        taxable_value=Decimal("50000.00"),
        cgst=Decimal("4500.00"),
        sgst=Decimal("4500.00"),
    )
    return r


def test_one_per_month_never_edited_replaced_whole() -> None:
    t = make_tenant()
    with tenant_context(t.tenant_id, t.user_id):
        r = upload(t)
        with pytest.raises(DatabaseError), transaction.atomic():
            upload(t)  # the same month twice
        with pytest.raises(DatabaseError), transaction.atomic():
            upload(t, period=date(2026, 10, 2))  # a month starts on the 1st
        with pytest.raises(DatabaseError), transaction.atomic():
            Gstr2bLine.objects.filter(gst_return=r).update(taxable_value=Decimal("1.00"))
        with pytest.raises(DatabaseError), transaction.atomic():
            Gstr2bReturn.objects.filter(pk=r.pk).update(doc_count=5)
        with connection.cursor() as cur:  # its lines go with it
            cur.execute("DELETE FROM gstr2b_returns WHERE id = %s", [r.pk])
        assert Gstr2bLine.objects.count() == 0
        upload(t)


def test_another_business_sees_none_of_it() -> None:
    a, b = make_tenant(), make_tenant("Other Builders")
    with tenant_context(a.tenant_id, a.user_id):
        upload(a)
    with tenant_context(b.tenant_id, b.user_id), connection.cursor() as cur:
        for table in ("gstr2b_returns", "gstr2b_lines"):
            cur.execute(f"SELECT count(*) FROM {table}")  # noqa: S608
            assert cur.fetchone() == (0,), table
