"""GSTR-2B upload and reconciliation through the API (Part B).

The October 2B has four documents from two suppliers; the books have three
GST bills from them in October and one expense:

- KST/101 (50000 + 9000): in the books as "KST-0101", same amounts: MATCHED
- KST/102 (10000 + 1800): in the books for 10000 + 1700: AMOUNTS_DIFFER
- CC/77 (20000 + 3600): in the books as "77" dated 2 days later: MATCHED
  by its value and date, the numbers noted
- CC/80 (5000 + 900): not in the books: NOT_IN_BOOKS
- a credit note CN-7: NOT_IN_BOOKS, it lowers the ITC
- the books' KST/105 (8000 + 1440, ITC claimed): NOT_IN_2B, at risk
"""

import json
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.expenses.models import Expense
from apps.parties.models import Party
from apps.payables.models import VendorBill
from apps.tenants.models import GstRegistration
from tests.factories import add_member, gstin, make_tenant, owner_member

STEEL = gstin("32", pan="AAACK1234M")
CEMENT = gstin("33", pan="AAACC5678P")

pytestmark = pytest.mark.django_db


def inv(number: str, day: str, txval: int, cgst: float, sgst: float) -> dict[str, Any]:
    return {"inum": number, "dt": day, "txval": txval, "cgst": cgst, "sgst": sgst, "pos": "32"}


class Books:
    def __init__(self, name: str = "Nair Constructions") -> None:
        self.t = make_tenant(name)
        self.owner = owner_member(self.t)
        with tenant_context(self.t.tenant_id, self.t.user_id):
            self.gstin = GstRegistration.objects.get(pk=self.t.registration_id).gstin
            self.steel = self.vendor("Kerala Steel Traders", STEEL)
            self.cement = self.vendor("Coastal Cement", CEMENT)
            self.bill(self.steel, "KST-0101", date(2026, 10, 10), "50000", "9000")
            self.bill(self.steel, "KST/102", date(2026, 10, 28), "10000", "1700")
            self.bill(self.steel, "KST/105", date(2026, 10, 30), "8000", "1440")
            self.bill(self.steel, "KST/090", date(2026, 9, 20), "1000", "180")  # September
            Expense.objects.create(
                vendor_party=self.cement,
                category="MATERIAL",
                expense_date=date(2026, 10, 17),
                description="Cement, 400 bags",
                vendor_bill_number="77",
                taxable_value=Decimal("20000.00"),
                gst_amount=Decimal("3600.00"),
                total_amount=Decimal("23600.00"),
                itc_eligible=True,
                created_by_id=self.t.user_id,
            )

    def vendor(self, name: str, number: str) -> Party:
        party: Party = Party.objects.create(
            display_name=name,
            gst_treatment="REGISTERED",
            gstin=number,
            state_code=number[:2],
            is_customer=False,
            is_vendor=True,
            created_by_id=self.t.user_id,
        )
        return party

    def bill(self, v: Party, number: str, day: date, value: str, tax: str) -> None:
        total = Decimal(value) + Decimal(tax)
        VendorBill.objects.create(
            vendor_party=v,
            bill_number=number,
            bill_date=day,
            category="MATERIAL",
            description="Steel",
            taxable_value=Decimal(value),
            gst_amount=Decimal(tax),
            total_amount=total,
            itc_eligible=True,
            net_payable=total,
            created_by_id=self.t.user_id,
        )

    def portal_file(self, gstin_: str | None = None) -> bytes:
        return json.dumps(
            {
                "data": {
                    "gstin": gstin_ or self.gstin,
                    "rtnprd": "102026",
                    "gendt": "14-11-2026",
                    "docdata": {
                        "b2b": [
                            {
                                "ctin": STEEL,
                                "trdnm": "Kerala Steel Traders",
                                "inv": [
                                    inv("KST/101", "10-10-2026", 50000, 4500, 4500),
                                    inv("KST/102", "28-10-2026", 10000, 900, 900),
                                ],
                            },
                            {
                                "ctin": CEMENT,
                                "trdnm": "Coastal Cement",
                                "inv": [
                                    {**inv("CC/77", "15-10-2026", 20000, 0, 0), "igst": 3600},
                                    {**inv("CC/80", "20-10-2026", 5000, 0, 0), "igst": 900},
                                ],
                            },
                        ],
                        "cdnr": [
                            {
                                "ctin": CEMENT,
                                "trdnm": "Coastal Cement",
                                "nt": [
                                    {
                                        "ntnum": "CN-7",
                                        "typ": "C",
                                        "dt": "25-10-2026",
                                        "txval": 1000,
                                        "igst": 180,
                                    }
                                ],
                            }
                        ],
                    },
                }
            }
        ).encode()

    def h(self, member: Any = None) -> dict[str, Any]:
        m = member or self.owner
        return {"HTTP_AUTHORIZATION": f"Bearer {m.access_token}"}

    def upload(self, data: bytes | None = None, member: Any = None) -> Any:
        return APIClient().post(
            "/api/v1/gstr2b-returns",
            {"file": SimpleUploadedFile("returns_102026_R2B.json", data or self.portal_file())},
            format="multipart",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
            **self.h(member),
        )

    def recon(self, return_id: str, member: Any = None, **query: str) -> Any:
        return APIClient().get(
            f"/api/v1/gstr2b-returns/{return_id}/reconciliation", query, **self.h(member)
        )


@pytest.fixture
def b() -> Books:
    return Books()


def test_upload_and_reconcile(b: Books) -> None:
    r = b.upload()
    assert r.status_code == 201, r.content
    up = r.json()
    assert (up["period"], up["doc_count"], up["gstin"]) == ("2026-10-01", 5, b.gstin)
    rec = b.recon(up["id"]).json()
    s = rec["summary"]
    assert (s["matched"], s["amounts_differ"], s["not_in_books"], s["not_in_2b"]) == (2, 1, 2, 1)
    # ITC per 2B: 9000 + 1800 + 3600 + 900 - 180 (the credit note)
    assert s["itc_in_2b"] == "15120.00"
    assert s["itc_matched"] == "12600.00"
    assert s["itc_not_in_books"] == "900.00"
    assert s["itc_at_risk"] == "1440.00"  # KST/105 (September's KST/090 is not this month)
    by_number = {
        (row["portal"] or row["books"])["doc_number" if row["portal"] else "number"]: row
        for row in rec["rows"]
    }
    assert by_number["KST/101"]["status"] == "MATCHED"
    assert by_number["KST/101"]["books"]["number"] == "KST-0101"
    differ = by_number["KST/102"]
    assert (differ["status"], differ["tax_difference"], differ["taxable_difference"]) == (
        "AMOUNTS_DIFFER",
        "100.00",
        "0.00",
    )
    cc = by_number["CC/77"]
    assert (cc["status"], cc["books"]["kind"]) == ("MATCHED", "EXPENSE")
    assert cc["note"] == "Numbers differ: theirs CC/77, ours 77."
    assert by_number["CC/80"]["status"] == "NOT_IN_BOOKS"
    assert by_number["CN-7"]["note"].startswith("A credit note")
    assert by_number["KST/105"]["status"] == "NOT_IN_2B"
    only = b.recon(up["id"], status="NOT_IN_2B").json()["rows"]
    assert [x["books"]["number"] for x in only] == ["KST/105"]


def test_recording_the_missing_bill_matches_it(b: Books) -> None:
    up = b.upload().json()
    with tenant_context(b.t.tenant_id, b.t.user_id):
        b.bill(b.cement, "CC/80", date(2026, 10, 20), "5000", "900")
    s = b.recon(up["id"]).json()["summary"]
    assert (s["matched"], s["not_in_books"]) == (3, 1)


def test_the_month_uploaded_again_replaces_it(b: Books) -> None:
    first = b.upload().json()
    second = b.upload().json()
    assert first["id"] != second["id"]
    listed = APIClient().get("/api/v1/gstr2b-returns", **b.h()).json()["results"]
    assert [x["id"] for x in listed] == [second["id"]]
    assert b.recon(first["id"]).status_code == 404


def test_checks(b: Books) -> None:
    r = b.upload(b.portal_file(gstin_=STEEL))
    assert (r.status_code, r.json()["errors"][0]["code"]) == (422, "other_gstin")
    r = b.upload(b"not json")
    assert (r.status_code, r.json()["errors"][0]["code"]) == (422, "not_gstr2b")


def test_who_may(b: Books) -> None:
    viewer, engineer = add_member(b.t, "VIEWER"), add_member(b.t, "SITE_ENGINEER")
    assert b.upload(member=viewer).status_code == 403
    up = b.upload().json()
    assert b.recon(up["id"], viewer).status_code == 200  # a CA with the Viewer role reads it
    assert b.recon(up["id"], engineer).status_code == 403


def test_another_business_reaches_none_of_it(b: Books) -> None:
    up = b.upload().json()
    other = Books("Other Builders")
    assert other.recon(up["id"]).status_code == 404
    assert APIClient().get("/api/v1/gstr2b-returns", **other.h()).json()["results"] == []
