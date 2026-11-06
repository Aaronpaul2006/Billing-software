"""Cash-flow forecast (Part B): money due in and out, week by week, as a range.

Each client bill is 323680.00 to collect (see test_statement.py); each vendor
bill is 50000 + 9000 GST less 1 % TDS on 50000 = 58500.00 to pay.
"""

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.banking.models import BankLine
from apps.core.tenancy import tenant_context
from apps.parties.models import Party
from tests.factories import add_member
from tests.payments.test_payments import Money

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
MONDAY = TODAY - timedelta(days=TODAY.weekday())
BILL = Decimal("323680.00")
VENDOR_BILL = Decimal("58500.00")


def days(n: int) -> str:
    return str(TODAY + timedelta(days=n))


class Forecast(Money):
    def __init__(self) -> None:
        super().__init__()
        with tenant_context(self.t.tenant_id, self.t.user_id):
            self.vendor = Party.objects.create(
                display_name="Ravi Kumar (labour contractor)",
                gst_treatment="UNREGISTERED",
                is_customer=False,
                is_vendor=True,
                pan="ABCPK1234L",
                created_by_id=self.t.user_id,
            )

    def client_bill(self, due: int) -> dict[str, Any]:
        bill = self.invoice(doc_date=days(-40), due_date=days(due))
        assert Decimal(bill["totals"]["net_receivable"]) == BILL
        return bill

    def vendor_bill(self, due: int | None, dated: int = -20) -> dict[str, Any]:
        r = APIClient().post(
            "/api/v1/vendor-bills",
            {
                "vendor_party_id": str(self.vendor.pk),
                "project_id": str(self.project.pk),
                "bill_number": f"RK/{uuid.uuid4().hex[:6]}",
                "bill_date": days(dated),
                "due_date": None if due is None else days(due),
                "category": "SUBCONTRACT",
                "description": "Brickwork",
                "taxable_value": "50000.00",
                "gst_amount": "9000.00",
                "tds_section": "194C",
                "tds_rate": "1.00",
            },
            format="json",
            **self.h(IDEMPOTENCY_KEY=str(uuid.uuid4())),
        )
        assert r.status_code == 201, r.content
        assert Decimal(r.json()["net_payable"]) == VENDOR_BILL
        return dict(r.json())

    def bank_line(self, account: str, on: int, balance: str | None) -> None:
        with tenant_context(self.t.tenant_id, self.t.user_id):
            BankLine.objects.create(
                account_label=account,
                line_date=TODAY + timedelta(days=on),
                narration="NEFT",
                money_in=Decimal("1.00"),
                balance=None if balance is None else Decimal(balance),
                fingerprint=uuid.uuid4().hex + uuid.uuid4().hex,
                created_by_id=self.t.user_id,
            )

    def forecast(self, member: Any = None, **query: Any) -> Any:
        return APIClient().get("/api/v1/reports/cash-flow", query, **self.h(member))


@pytest.fixture
def f() -> Forecast:
    return Forecast()


def week_of(n: int) -> int:
    return ((TODAY + timedelta(days=n)) - MONDAY).days // 7


def test_each_week_shows_what_falls_due_and_a_range(f: Forecast) -> None:
    soon, later = f.client_bill(due=1), f.client_bill(due=20)
    f.client_bill(due=-5)  # overdue: no honest week for it
    f.client_bill(due=200)  # beyond the forecast
    late = f.vendor_bill(due=-3, dated=-30)
    f.vendor_bill(due=None, dated=-2)  # no due date and dated before today: overdue
    owed = f.vendor_bill(due=8, dated=-1)
    f.bank_line("HDFC 1234", -3, "500000.00")
    f.bank_line("HDFC 1234", -1, "400000.00")  # the newest balance counts
    f.bank_line("HDFC 1234", 0, None)  # a line without a balance is skipped
    f.bank_line("SBI 9876", -2, "100000.00")

    r = f.forecast()
    assert r.status_code == 200, r.content
    cf = r.json()
    assert cf["as_of"] == str(TODAY)
    assert cf["cash_today"] == "500000.00"
    assert len(cf["cash_sources"]) == 2
    assert cf["overdue_in"] == str(BILL)
    assert cf["overdue_out"] == str(2 * VENDOR_BILL)
    weeks = cf["weeks"]
    assert len(weeks) == 8
    assert weeks[0]["start"] == str(MONDAY)
    assert weeks[0]["end"] == str(MONDAY + timedelta(days=6))

    expected_in = {week_of(1): BILL}
    expected_in[week_of(20)] = expected_in.get(week_of(20), Decimal(0)) + BILL
    expected_out = {week_of(8): VENDOR_BILL}
    low = Decimal("500000.00") - 2 * VENDOR_BILL
    high = low + BILL
    for i, w in enumerate(weeks):
        money_in = expected_in.get(i, Decimal("0.00"))
        money_out = expected_out.get(i, Decimal("0.00"))
        assert Decimal(w["money_in"]) == money_in, i
        assert Decimal(w["money_out"]) == money_out, i
        low += money_in - money_out
        high += money_in - money_out
        assert (Decimal(w["balance_low"]), Decimal(w["balance_high"])) == (low, high), i

    first = weeks[week_of(1)]["bills_in"][0]
    assert first["id"] == soon["id"]
    assert (first["kind"], first["number"], first["party_name"]) == (
        "BILL",
        soon["doc_number"],
        "Skyline Developers",
    )
    assert any(b["id"] == later["id"] for b in weeks[week_of(20)]["bills_in"])
    out = weeks[week_of(8)]["bills_out"]
    assert [(b["id"], b["kind"], b["outstanding"]) for b in out] == [
        (owed["id"], "VENDOR_BILL", str(VENDOR_BILL))
    ]
    assert late["id"] not in {b["id"] for w in weeks for b in w["bills_out"]}
    lowest = min(weeks, key=lambda w: Decimal(w["balance_low"]))
    assert cf["lowest_balance"] == lowest["balance_low"]
    assert cf["lowest_week_start"] == lowest["start"]


def test_paid_bills_drop_out_and_part_payments_count_what_is_left(f: Forecast) -> None:
    bill = f.client_bill(due=2)
    paid = f.pay("100000.00", allocations=[{"document_id": bill["id"], "amount": "100000.00"}])
    assert paid.status_code == 201, paid.content
    vendor = f.vendor_bill(due=3, dated=-1)
    r = APIClient().post(
        "/api/v1/vendor-payments",
        {
            "vendor_party_id": str(f.vendor.pk),
            "payment_date": days(-1),
            "amount": str(VENDOR_BILL),
            "mode": "BANK_TRANSFER",
            "allocations": [{"vendor_bill_id": vendor["id"], "amount": str(VENDOR_BILL)}],
        },
        format="json",
        **f.h(IDEMPOTENCY_KEY=str(uuid.uuid4())),
    )
    assert r.status_code == 201, r.content
    weeks = f.forecast().json()["weeks"]
    assert Decimal(weeks[week_of(2)]["money_in"]) == BILL - Decimal("100000.00")
    assert all(w["bills_out"] == [] for w in weeks)


def test_without_a_statement_it_shows_the_change_only(f: Forecast) -> None:
    f.client_bill(due=3)
    cf = f.forecast(weeks=2).json()
    assert (cf["cash_today"], cf["cash_sources"]) == (None, [])
    assert len(cf["weeks"]) == 2
    assert Decimal(cf["weeks"][-1]["balance_low"]) == BILL  # due within 2 weeks


def test_weeks_are_limited(f: Forecast) -> None:
    for bad in ("0", "14", "x"):
        r = f.forecast(weeks=bad)
        assert r.status_code == 422, (bad, r.content)
    assert len(f.forecast(weeks=13).json()["weeks"]) == 13


def test_who_may_see_it(f: Forecast) -> None:
    assert f.forecast(add_member(f.t, "SITE_ENGINEER")).status_code == 403
    assert f.forecast(add_member(f.t, "VIEWER")).status_code == 200


def test_another_business_sees_none_of_it(f: Forecast) -> None:
    f.client_bill(due=2)
    f.vendor_bill(due=2, dated=-1)
    f.bank_line("HDFC 1234", -1, "900000.00")
    other = Forecast()
    cf = other.forecast().json()
    assert cf["cash_today"] is None
    assert (cf["overdue_in"], cf["overdue_out"]) == ("0.00", "0.00")
    assert all(w["bills_in"] == [] and w["bills_out"] == [] for w in cf["weeks"])
