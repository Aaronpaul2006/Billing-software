"""TDS certificates and reconciliation (Phase 3.4).

VILLA-1 deducts 1 % income-tax TDS (s.194C) on the taxable value, FY 2026-27:
  Q2  2026-08-10  10 cum @ 6800 =  68000  -> TDS   680
  Q3  2026-10-19  42.5 cum       = 289000  -> TDS  2890   (twice: 5780)
  Q3  a cancelled bill and a bill without a project (no TDS) do not count
"""

import uuid
from datetime import date
from typing import Any

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.parties.models import Party
from apps.reports.serializers import fy_start
from tests.documents.test_drafts import RCC
from tests.factories import add_member
from tests.payments.test_payments import Money, problem

pytestmark = pytest.mark.django_db
TAN = "BLRS12345E"


class Tds(Money):
    def certificate(self, member: Any = None, **body: Any) -> Any:
        return APIClient().post(
            "/api/v1/tds-certificates",
            {
                "party_id": str(self.client.pk),
                "deductor_tan": TAN.lower(),
                "fy_start_year": 2026,
                "quarter": 3,
                "certificate_number": "QWERTYU",
                "certificate_date": "2027-02-10",
                "amount_credited": "578000.00",
                "tds_amount": "5780.00",
                **body,
            },
            format="json",
            **self.h(member, IDEMPOTENCY_KEY=str(uuid.uuid4())),
        )

    def reconcile(self, member: Any = None, **params: str) -> Any:
        return APIClient().get(
            "/api/v1/reports/tds-reconciliation", {"fy": "2026", **params}, **self.h(member)
        )


@pytest.fixture
def t() -> Tds:
    return Tds()


def test_record_correct_and_delete_a_certificate(t: Tds) -> None:
    r = t.certificate()
    assert r.status_code == 201, r.content
    cert = r.json()
    assert (cert["deductor_tan"], cert["section"], cert["tds_amount"], r["ETag"]) == (
        TAN,
        "194C",
        "5780.00",
        '"v1"',
    )
    url, api = f"/api/v1/tds-certificates/{cert['id']}", APIClient()
    fixed = api.patch(url, {"tds_amount": "5000.00"}, format="json", **t.h(IF_MATCH='"v1"'))
    assert (fixed.status_code, fixed.json()["tds_amount"], fixed["ETag"]) == (
        200,
        "5000.00",
        '"v2"',
    )
    assert problem(t.certificate()) == (409, "certificate_exists")  # same TAN and number
    assert t.certificate(deductor_tan="MUMS12345F").status_code == 201  # another TAN may reuse it
    rows = api.get("/api/v1/tds-certificates", {"deductor_tan": TAN}, **t.h()).json()["results"]
    assert [c["id"] for c in rows] == [cert["id"]]
    assert api.delete(url, **t.h()).status_code == 204
    assert api.get(url, **t.h()).status_code == 404


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"deductor_tan": "BLRS1234E"}, "invalid_tan"),
        ({"quarter": 5}, "max_value"),
        ({"tds_amount": 5780}, "not_a_string"),
        ({"tds_amount": "-1.00"}, "min_value"),
        ({"certificate_number": "has space"}, "invalid"),
        ({"party_id": str(uuid.uuid4())}, "not_found"),
    ],
)
def test_validation(t: Tds, body: dict[str, Any], code: str) -> None:
    assert problem(t.certificate(**body)) == (422, code)


def test_certificates_come_from_customers(t: Tds) -> None:
    with tenant_context(t.t.tenant_id, t.t.user_id):
        vendor = Party.objects.create(
            display_name="Coastal Cement",
            gst_treatment="UNREGISTERED",
            is_customer=False,
            is_vendor=True,
            created_by_id=t.t.user_id,
        )
    assert problem(t.certificate(party_id=str(vendor.pk))) == (422, "not_a_customer")


def test_reconciliation_by_client_and_quarter(t: Tds) -> None:
    t.invoice(doc_date="2026-08-10", lines=[{**RCC, "quantity": "10"}])
    t.invoice()
    t.invoice()
    cancelled = t.invoice()
    APIClient().post(
        f"/api/v1/documents/{cancelled['id']}/cancel",
        {"reason": "duplicate"},
        format="json",
        **t.h(IF_MATCH=f'"v{cancelled["version"]}"', IDEMPOTENCY_KEY=str(uuid.uuid4())),
    )
    t.invoice(project_id=None)  # no project: no deductions
    t.certificate(quarter=2, certificate_number="ASDFGHJ", tds_amount="680.00")
    t.certificate(tds_amount="5000.00")  # Q3: 780 short
    t.certificate(quarter=1, certificate_number="ZXCVBNM", tds_amount="100.00")  # no bills in Q1

    r = t.reconcile()
    assert r.status_code == 200, r.content
    body = r.json()
    rows = [
        (
            x["quarter"],
            x["bill_count"],
            x["taxable_value"],
            x["expected"],
            x["certified"],
            x["difference"],
            x["status"],
            x["deductor_tans"],
        )
        for x in body["results"]
    ]
    assert rows == [
        (1, 0, "0.00", "0.00", "100.00", "100.00", "EXCESS", TAN),
        (2, 1, "68000.00", "680.00", "680.00", "0.00", "MATCHED", TAN),
        (3, 2, "578000.00", "5780.00", "5000.00", "-780.00", "SHORT", TAN),
    ]
    today = timezone.localdate()
    dues = {x["quarter"]: (x["certificate_due"], x["overdue"]) for x in body["results"]}
    assert dues[2] == ("2026-11-15", False)  # matched: never overdue
    assert dues[3] == ("2027-02-15", today > date(2027, 2, 15))
    assert body["totals"] == {
        "expected": "6460.00",
        "certified": "5780.00",
        "difference": "-680.00",
    }
    assert t.reconcile(fy="2025").json()["results"] == []


def test_not_received_and_defaults(t: Tds) -> None:
    t.invoice()
    [row] = t.reconcile().json()["results"]
    assert (row["status"], row["certified"], row["deductor_tans"], row["certificate_count"]) == (
        "NOT_RECEIVED",
        "0.00",
        None,
        0,
    )
    default = APIClient().get("/api/v1/reports/tds-reconciliation", **t.h()).json()
    assert default["fy_start_year"] == fy_start(timezone.localdate()).year
    assert t.reconcile(party_id=str(uuid.uuid4())).json()["results"] == []
    assert problem(t.reconcile(fy="1999")) == (422, "min_value")


def test_roles(t: Tds) -> None:
    engineer, viewer = add_member(t.t, "SITE_ENGINEER"), add_member(t.t, "VIEWER")
    assert problem(t.certificate(member=engineer)) == (403, "permission_denied")
    assert problem(t.certificate(member=viewer)) == (403, "permission_denied")
    assert APIClient().get("/api/v1/tds-certificates", **t.h(viewer)).status_code == 200
    assert problem(t.reconcile(member=engineer)) == (403, "permission_denied")
    assert t.reconcile(member=viewer).status_code == 200


@pytest.mark.parametrize(
    ("day", "quarter"),
    [
        ("2026-04-01", 1),
        ("2026-06-30", 1),
        ("2026-07-01", 2),
        ("2026-09-30", 2),
        ("2026-10-01", 3),
        ("2026-12-31", 3),
        ("2027-01-01", 4),
        ("2027-03-31", 4),
    ],
)
def test_financial_year_quarters(day: str, quarter: int) -> None:
    from django.db import connection

    from apps.reports.queries import FY_QUARTER_SQL

    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {FY_QUARTER_SQL} FROM (SELECT %s::date AS doc_date) d", [day])  # noqa: S608 - a constant
        assert cursor.fetchone() == (quarter,)
