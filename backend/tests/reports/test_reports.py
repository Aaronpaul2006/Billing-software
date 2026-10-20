"""Reports against one hand-computed scenario (Phase 2.4).

October 2026, tenant in Kerala (32):
  INV/0001  2026-10-19  VILLA (site 32)  42.5 cum x 6800 @18 %   taxable 289000  CGST+SGST 52020
            grand 341020, retention 14450, TDS 2890 -> net 323680
  INV/0002  2026-10-20  BLR (site 29)    10 x 1000 @12 %         taxable  10000  IGST 1200
            grand  11200, retention 500, TDS 100 -> net 10600
  INV/0003  issued, then cancelled                                (counts nowhere)
  QT/0001   quotation                                             (not revenue)
  CN/0001   2026-10-30  against INV/0001, 1 cum @18 %             taxable   6800  tax 1224, 8024
  payments: 300000 allocated to INV/0001 (25 Oct), 5000 advance unallocated (26 Oct)
  expenses on VILLA: cement 38000 + GST 10640 (ITC claimable), labour 42000 (no GST)
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.expenses.models import Expense
from apps.reports.serializers import previous_period
from tests.documents.test_drafts import RCC
from tests.factories import add_member
from tests.payments.test_credit_notes import Credits

pytestmark = pytest.mark.django_db
OCT = {"from": "2026-10-01", "to": "2026-10-31"}


class Scenario(Credits):
    def __init__(self) -> None:
        super().__init__()
        self.inv1 = self.invoice()
        self.blr = self.make_project("BLR-1", "29")
        self.inv2 = self.invoice(
            project_id=str(self.blr.pk),
            doc_date="2026-10-20",
            lines=[{**RCC, "quantity": "10", "rate": "1000.00", "gst_rate": "12.00"}],
        )
        inv3 = self.invoice()
        cancel = APIClient().post(
            f"/api/v1/documents/{inv3['id']}/cancel",
            {"reason": "duplicate"},
            format="json",
            **self.h(IF_MATCH=f'"v{inv3["version"]}"'),
        )
        assert cancel.status_code == 200, cancel.content
        self.invoice(doc_type="QUOTATION")
        self.cn = self.credit_note(self.inv1)
        self.pay("300000.00", [{"document_id": self.inv1["id"], "amount": "300000.00"}])
        self.pay("5000.00", payment_date="2026-10-26")
        with tenant_context(self.t.tenant_id, self.t.user_id):
            for desc, taxable, gst, itc, category in (
                ("Cement", "38000", "10640", True, "MATERIAL"),
                ("Masons", "42000", "0", False, "LABOUR"),
            ):
                Expense.objects.create(
                    project=self.project,
                    category=category,
                    expense_date="2026-10-22",
                    description=desc,
                    taxable_value=Decimal(taxable),
                    gst_amount=Decimal(gst),
                    total_amount=Decimal(taxable) + Decimal(gst),
                    itc_eligible=itc,
                    created_by_id=self.t.user_id,
                )

    def get(self, path: str, member: Any = None, **params: str) -> Any:
        return APIClient().get(f"/api/v1/reports/{path}", params, **self.h(member))


@pytest.fixture
def s() -> Scenario:
    return Scenario()


def test_summary_and_previous_period(s: Scenario) -> None:
    r = s.get("summary", **OCT)
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["current"] == {
        "billed": "344196.00",  # 341020 + 11200 - 8024
        "taxable": "292200.00",  # 289000 + 10000 - 6800
        "tax": "51996.00",  # 52020 + 1200 - 1224
        "collected": "305000.00",  # both payments, incl. the unallocated advance
        "expenses": "90640.00",  # 48640 + 42000
        "outstanding": "34280.00",  # (323680 - 300000) + 10600
    }
    assert body["previous_period"] == {"from": "2026-09-01", "to": "2026-09-30"}
    assert body["previous"]["billed"] == "0.00"


def test_books(s: Scenario) -> None:
    gst = s.get("summary", book="GST", **OCT).json()["current"]
    assert (gst["billed"], gst["collected"]) == ("344196.00", "300000.00")  # allocated only
    non_gst = s.get("summary", book="NON_GST", **OCT).json()["current"]
    assert (non_gst["billed"], non_gst["collected"], non_gst["outstanding"]) == (
        "0.00",
        "0.00",
        "0.00",  # quotations are not revenue
    )


def test_billing_by_month(s: Scenario) -> None:
    rows = s.get("billing-by-month", **OCT).json()["results"]
    assert rows == [
        {
            "month": "2026-10-01",
            "book": "GST",
            "document_count": 3,
            "taxable_value": "292200.00",
            "tax": "51996.00",
            "billed": "344196.00",
        }
    ]


def test_receivables_by_party(s: Scenario) -> None:
    body = s.get("receivables").json()
    [row] = body["results"]
    assert (row["display_name"], row["document_count"], row["total"]) == (
        "Skyline Developers",
        2,
        "34280.00",
    )
    buckets = ("not_due", "days_1_30", "days_31_60", "days_61_90", "days_90_plus")
    assert sum(Decimal(row[b]) for b in buckets) == Decimal("34280.00")
    assert body["totals"]["total"] == "34280.00"


def _bucket(days_overdue: int) -> str:
    if days_overdue <= 0:
        return "not_due"
    for limit, name in ((30, "days_1_30"), (60, "days_31_60"), (90, "days_61_90")):
        if days_overdue <= limit:
            return name
    return "days_90_plus"


def test_ageing_buckets_follow_the_due_date() -> None:
    c = Credits()
    today = timezone.localdate()
    due_future = today + timedelta(days=30)
    past = date(2026, 10, 19)  # doc date of the series' financial year
    c.invoice(due_date=str(due_future))
    c.invoice(due_date=str(past))
    row = APIClient().get("/api/v1/reports/receivables", **c.h()).json()["results"][0]
    assert row["not_due"] == "323680.00"
    assert row[_bucket((today - past).days)] == "323680.00"


def test_project_report_margin(s: Scenario) -> None:
    rows = {r["code"]: r for r in s.get("projects").json()["results"]}
    villa = rows["VILLA-1"]
    assert (villa["billed_taxable"], villa["retention_held"], villa["tds_deducted"]) == (
        "282200.00",
        "14450.00",
        "2890.00",  # 289000 - 6800 (credit note)
    )
    assert (villa["outstanding"], villa["cost"], villa["margin"]) == (
        "23680.00",
        "80000.00",
        "202200.00",  # cement GST is claimable, so not a cost
    )
    detail = s.get(f"projects/{s.blr.pk}").json()
    assert (detail["billed_taxable"], detail["outstanding"], detail["margin"]) == (
        "10000.00",
        "10600.00",
        "10000.00",
    )
    assert s.get(f"projects/{uuid.uuid4()}").status_code == 404


def test_gst_summary(s: Scenario) -> None:
    body = s.get("gst-summary", period="2026-10").json()
    assert body["results"] == [
        {
            "supply": "B2B",
            "gst_rate": "12.00",
            "document_count": 1,
            "taxable_value": "10000.00",
            "cgst": "0.00",
            "sgst": "0.00",
            "igst": "1200.00",
            "cess": "0.00",
        },
        {
            "supply": "B2B",
            "gst_rate": "18.00",
            "document_count": 2,
            "taxable_value": "282200.00",
            "cgst": "25398.00",
            "sgst": "25398.00",
            "igst": "0.00",
            "cess": "0.00",
        },
    ]
    assert body["totals"]["taxable_value"] == "292200.00"
    assert s.get("gst-summary", period="2026-09").json()["results"] == []


def test_validation_and_roles(s: Scenario) -> None:
    def code(r: Any) -> tuple[int, str]:
        b = r.json()
        return r.status_code, (
            b["errors"][0]["code"] if b["code"] == "validation_error" else b["code"]
        )

    assert code(s.get("summary", **{"from": "2026-11-01", "to": "2026-10-01"})) == (
        422,
        "invalid_dates",
    )
    assert code(s.get("summary", **{"from": "2015-01-01", "to": "2026-10-01"})) == (
        422,
        "range_too_long",
    )
    assert code(s.get("gst-summary", period="2026-13")) == (422, "invalid")
    assert code(s.get("summary", member=add_member(s.t, "SITE_ENGINEER"))) == (
        403,
        "permission_denied",
    )
    assert s.get("summary", member=add_member(s.t, "VIEWER")).status_code == 200


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("2026-10-01", "2026-10-31", ("2026-09-01", "2026-09-30")),
        ("2026-03-01", "2026-03-31", ("2026-02-01", "2026-02-28")),
        ("2026-01-01", "2026-03-31", ("2025-10-01", "2025-12-31")),
        ("2026-04-01", "2027-03-31", ("2025-04-01", "2026-03-31")),
        ("2026-10-11", "2026-10-20", ("2026-10-01", "2026-10-10")),
    ],
)
def test_previous_period(start: str, end: str, expected: tuple[str, str]) -> None:
    prev = previous_period(date.fromisoformat(start), date.fromisoformat(end))
    assert tuple(d.isoformat() for d in prev) == expected
