"""Bank line rules the database enforces (Part B)."""

import hashlib
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.db import DatabaseError, transaction

from apps.banking.models import BankLine
from apps.core.tenancy import tenant_context
from apps.parties.models import Party
from apps.payments.models import Payment
from tests.factories import TenantFixture, make_tenant

pytestmark = pytest.mark.django_db


def line(t: TenantFixture, n: int = 1, **kw: Any) -> BankLine:
    fields: dict[str, Any] = {
        "account_label": "HDFC 1234",
        "line_date": date(2026, 10, 5),
        "narration": "NEFT CR SKYLINE",
        "money_in": Decimal("1000.00"),
        "fingerprint": hashlib.sha256(str(n).encode()).hexdigest(),
        "created_by_id": t.user_id,
        **kw,
    }
    created: BankLine = BankLine.objects.create(**fields)
    return created


def payment(t: TenantFixture) -> Payment:
    client = Party.objects.create(
        display_name="Skyline", gst_treatment="UNREGISTERED", created_by_id=t.user_id
    )
    created: Payment = Payment.objects.create(
        party=client,
        payment_date=date(2026, 10, 5),
        amount=Decimal("1000.00"),
        mode="BANK_TRANSFER",
        created_by_id=t.user_id,
    )
    return created


def refused(**kw: Any) -> None:
    with pytest.raises(DatabaseError), transaction.atomic():
        BankLine.objects.create(**kw)


def test_money_in_or_out_and_matched_means_linked() -> None:
    t = make_tenant()
    with tenant_context(t.tenant_id, t.user_id):
        base = {
            "account_label": "HDFC",
            "line_date": date(2026, 10, 5),
            "narration": "x",
            "fingerprint": "a" * 64,
            "created_by_id": t.user_id,
        }
        refused(**base, money_in=Decimal("1"), money_out=Decimal("1"))  # both
        refused(**base)  # neither
        refused(**base, money_in=Decimal("1"), status="MATCHED")  # matched to nothing
        p = payment(t)
        refused(**base, money_out=Decimal("1"), payment=p, status="MATCHED")  # out, but a receipt
        first = line(t, 1, payment=p, status="MATCHED")
        assert first.status == "MATCHED"
        with pytest.raises(DatabaseError), transaction.atomic():
            line(t, 2, payment=p, status="MATCHED")  # one payment, one bank line


def test_the_same_line_is_imported_once() -> None:
    t = make_tenant()
    with tenant_context(t.tenant_id, t.user_id):
        line(t, 7)
        with pytest.raises(DatabaseError), transaction.atomic():
            line(t, 7)


def test_another_business_sees_none_of_it() -> None:
    a, b = make_tenant(), make_tenant("Other Builders")
    with tenant_context(a.tenant_id, a.user_id):
        line(a)
    with tenant_context(b.tenant_id, b.user_id):
        assert BankLine.objects.count() == 0
