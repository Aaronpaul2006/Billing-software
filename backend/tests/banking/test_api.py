"""Bank statement API (Part B): import a statement, then match each line by hand.

The invoice from the payments tests: 341020.00 with retention and TDS off, so
the client owes 323680.00 on it.
"""

import uuid
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.parties.models import Party
from tests.factories import add_member, make_tenant, owner_member
from tests.payments.test_payments import Money

pytestmark = pytest.mark.django_db

OWED = "323680.00"


def statement(*rows: str) -> bytes:
    head = "Date,Narration,Chq./Ref.No.,Withdrawal Amt.,Deposit Amt.,Closing Balance\n"
    return (head + "\n".join(rows) + "\n").encode()


FILE = statement(
    '19/10/26,NEFT CR-SBIN0001-SKYLINE DEVELOPERS,UTR778899001,,"3,23,680.00","3,23,680.00"',
    '20/10/26,NEFT CR-HDFC-SKYLINE DEVELOPERS,UTR554433221,,"50,000.00","3,73,680.00"',
    '21/10/26,CHQ PAID-RAVI KUMAR,000123,"58,500.00",,"3,15,180.00"',
    "22/10/26,SMS CHARGES,,17.70,,3315162.30",
)


class Bank(Money):
    def __init__(self) -> None:
        super().__init__()
        with tenant_context(self.t.tenant_id, self.t.user_id):
            self.vendor = Party.objects.create(
                display_name="Ravi Kumar",
                gst_treatment="UNREGISTERED",
                is_customer=False,
                is_vendor=True,
                pan="ABCPK1234L",
                created_by_id=self.t.user_id,
            )

    def upload(self, url: str, data: bytes, member: Any = None, **form: Any) -> Any:
        return APIClient().post(
            url,
            {"file": SimpleUploadedFile("statement.csv", data, "text/csv"), **form},
            format="multipart",
            **self.h(member, IDEMPOTENCY_KEY=str(uuid.uuid4())),
        )

    def lines(self, **query: Any) -> list[dict[str, Any]]:
        r = APIClient().get("/api/v1/bank-lines", query, **self.h())
        assert r.status_code == 200, r.content
        return list(r.json()["results"])

    def act(self, line: dict[str, Any], action: str, body: dict[str, Any] | None = None) -> Any:
        return APIClient().post(
            f"/api/v1/bank-lines/{line['id']}/{action}",
            body or {},
            format="json",
            **self.h(IF_MATCH=f'"v{line["version"]}"', IDEMPOTENCY_KEY=str(uuid.uuid4())),
        )

    def line(self, narration_start: str) -> dict[str, Any]:
        return next(x for x in self.lines() if x["narration"].startswith(narration_start))


@pytest.fixture
def bank() -> Bank:
    return Bank()


def test_preview_then_import_and_a_second_import_adds_nothing(bank: Bank) -> None:
    preview = bank.upload("/api/v1/bank-statements/preview", FILE)
    assert preview.status_code == 200, preview.content
    body = preview.json()
    assert (body["ready"], body["line_count"]) == (True, 4)
    assert body["lines"][0]["money_in"] == OWED
    assert bank.lines() == []  # a preview saves nothing
    first = bank.upload("/api/v1/bank-statements/import", FILE, account_label="HDFC 1234")
    assert first.status_code == 201, first.content
    assert (first.json()["added"], first.json()["duplicates"]) == (4, 0)
    again = bank.upload("/api/v1/bank-statements/import", FILE, account_label="HDFC 1234")
    assert (again.json()["added"], again.json()["duplicates"]) == (0, 4)
    no_name = bank.upload("/api/v1/bank-statements/import", FILE)
    assert no_name.json()["errors"][0]["code"] == "required"
    accounts = APIClient().get("/api/v1/bank-lines/accounts", **bank.h()).json()
    assert accounts == {"results": ["HDFC 1234"]}


def test_unknown_columns_are_chosen_and_then_imported(bank: Bank) -> None:
    odd = b"When,What,Out,In\n19/10/2026,Client,,1000.00\n"
    preview = bank.upload("/api/v1/bank-statements/preview", odd).json()
    assert (preview["ready"], preview["headers"]) == (False, ["When", "What", "Out", "In"])
    refused = bank.upload("/api/v1/bank-statements/import", odd, account_label="SBI")
    assert refused.json()["errors"][0]["code"] == "columns_not_found"
    mapping = '{"date": "When", "narration": "What", "money_out": "Out", "money_in": "In"}'
    done = bank.upload("/api/v1/bank-statements/import", odd, account_label="SBI", mapping=mapping)
    assert done.json()["added"] == 1


def test_suggestions_rank_the_recorded_payment_with_the_same_utr_first(bank: Bank) -> None:
    inv = bank.invoice()
    paid = bank.pay("50000.00", payment_date="2026-10-20", reference="UTR554433221").json()
    bank.upload("/api/v1/bank-statements/import", FILE, account_label="HDFC 1234")
    received = bank.line("NEFT CR-HDFC")
    assert received["suggestions"][0]["kind"] == "payment"
    assert received["suggestions"][0]["id"] == paid["id"]
    owed = bank.line("NEFT CR-SBIN")
    assert owed["suggestions"][0] == {
        "kind": "bill",
        "id": inv["id"],
        "party_id": str(bank.client.pk),
        "party_name": "Skyline Developers",
        "title": "Bill INV/0001",
        "score": owed["suggestions"][0]["score"],
    }


def test_match_reopen_and_one_payment_one_line(bank: Bank) -> None:
    paid = bank.pay("50000.00", payment_date="2026-10-20").json()
    bank.upload("/api/v1/bank-statements/import", FILE, account_label="HDFC 1234")
    line = bank.line("NEFT CR-HDFC")
    wrong = bank.act(bank.line("NEFT CR-SBIN"), "match", {"payment_id": paid["id"]})
    assert wrong.json()["errors"][0]["code"] == "amount_mismatch"
    done = bank.act(line, "match", {"payment_id": paid["id"]})
    assert done.status_code == 200, done.content
    assert (done.json()["status"], done.json()["payment_id"]) == ("MATCHED", paid["id"])
    assert done.json()["suggestions"] == []
    again = bank.act(done.json(), "match", {"payment_id": paid["id"]})
    assert again.json()["code"] == "bank_line_closed"
    reopened = bank.act(done.json(), "reopen")
    assert (reopened.json()["status"], reopened.json()["payment_id"]) == ("OPEN", None)


def test_record_a_payment_from_a_line_and_settle_the_bill(bank: Bank) -> None:
    inv = bank.invoice()
    bank.upload("/api/v1/bank-statements/import", FILE, account_label="HDFC 1234")
    line = bank.line("NEFT CR-SBIN")
    r = bank.act(
        line,
        "record",
        {
            "party_id": str(bank.client.pk),
            "allocations": [{"document_id": inv["id"], "amount": OWED}],
        },
    )
    assert r.status_code == 200, r.content
    assert r.json()["status"] == "MATCHED"
    payment = APIClient().get(f"/api/v1/payments/{r.json()['payment_id']}", **bank.h()).json()
    assert (payment["payment_date"], payment["amount"], payment["reference"]) == (
        "2026-10-19",
        OWED,
        "UTR778899001",
    )
    bill = APIClient().get(f"/api/v1/documents/{inv['id']}", **bank.h()).json()
    assert bill["totals"]["outstanding"] == "0.00"


def test_money_out_records_a_payment_to_a_vendor(bank: Bank) -> None:
    created = (
        APIClient()
        .post(
            "/api/v1/vendor-bills",
            {
                "vendor_party_id": str(bank.vendor.pk),
                "bill_number": "RK/1",
                "bill_date": "2026-10-10",
                "category": "SUBCONTRACT",
                "description": "Brickwork",
                "taxable_value": "50000.00",
                "gst_amount": "9000.00",
                "tds_section": "194C",
                "tds_rate": "1.00",
            },
            format="json",
            **bank.h(IDEMPOTENCY_KEY=str(uuid.uuid4())),
        )
        .json()
    )
    bank.upload("/api/v1/bank-statements/import", FILE, account_label="HDFC 1234")
    out = bank.line("CHQ PAID")
    assert out["suggestions"][0]["kind"] == "vendor_bill"
    r = bank.act(
        out,
        "record",
        {
            "vendor_party_id": str(bank.vendor.pk),
            "vendor_allocations": [{"vendor_bill_id": created["id"], "amount": "58500.00"}],
        },
    )
    assert r.status_code == 200, r.content
    assert r.json()["vendor_payment_id"]
    bill = APIClient().get(f"/api/v1/vendor-bills/{created['id']}", **bank.h()).json()
    assert bill["outstanding"] == "0.00"


def test_bank_charges_are_ignored_with_a_note(bank: Bank) -> None:
    bank.upload("/api/v1/bank-statements/import", FILE, account_label="HDFC 1234")
    r = bank.act(bank.line("SMS"), "ignore", {"note": "bank charges"})
    assert (r.json()["status"], r.json()["note"]) == ("IGNORED", "bank charges")
    assert [x["narration"] for x in bank.lines(status="OPEN", direction="OUT")] == [
        "CHQ PAID-RAVI KUMAR"
    ]


def test_only_those_who_record_payments(bank: Bank) -> None:
    viewer = add_member(bank.t, "VIEWER")
    assert (
        bank.upload(
            "/api/v1/bank-statements/import", FILE, viewer, account_label="HDFC"
        ).status_code
        == 403
    )
    assert APIClient().get("/api/v1/bank-lines", **bank.h(viewer)).status_code == 403


def test_another_business_reaches_none_of_it(bank: Bank) -> None:
    bank.upload("/api/v1/bank-statements/import", FILE, account_label="HDFC 1234")
    line = bank.line("SMS")
    other_t = make_tenant("Other Builders")
    other = owner_member(other_t)
    h: dict[str, Any] = {
        "HTTP_AUTHORIZATION": f"Bearer {other.access_token}",
        "HTTP_IF_MATCH": '"v1"',
        "HTTP_IDEMPOTENCY_KEY": str(uuid.uuid4()),
    }
    for action in ("match", "record", "ignore", "reopen"):
        r = APIClient().post(f"/api/v1/bank-lines/{line['id']}/{action}", {}, format="json", **h)
        assert r.status_code == 404, (action, r.content)
    listed = APIClient().get("/api/v1/bank-lines", HTTP_AUTHORIZATION=h["HTTP_AUTHORIZATION"])
    assert listed.json()["results"] == []
    accounts = APIClient().get(
        "/api/v1/bank-lines/accounts", HTTP_AUTHORIZATION=h["HTTP_AUTHORIZATION"]
    )
    assert accounts.json() == {"results": []}
    assert bank.line("SMS")["status"] == "OPEN"
