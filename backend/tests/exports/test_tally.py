"""Tally XML export (B.16): vouchers that balance, Tally's signs and bill references."""

import uuid
from decimal import Decimal
from typing import Any
from xml.etree.ElementTree import Element

import pytest
from defusedxml import ElementTree
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.exports.tally import build_tally
from apps.parties.models import Party
from apps.tenants.models import DocumentSeries
from tests.documents.test_drafts import RCC
from tests.factories import add_member, make_tenant, owner_member
from tests.payments.test_payments import Money

pytestmark = pytest.mark.django_db
PERIOD = {"from": "2026-04-01", "to": "2027-03-31"}


@pytest.fixture
def m() -> Money:
    world = Money()
    with tenant_context(world.t.tenant_id, world.t.user_id):
        DocumentSeries.objects.create(
            gst_registration_id=world.t.registration_id,
            doc_type="CREDIT_NOTE",
            fy_start_year=2026,
            prefix="CN/",
        )
    return world


def build(m: Money) -> tuple[Element, int, list[str]]:
    with tenant_context(m.t.tenant_id, m.t.user_id):
        body, name, count, warnings = build_tally(m.t.tenant_id, PERIOD)
    assert name == "tally-vouchers-2026-04-01-to-2027-03-31.xml"
    assert body.decode("ascii")  # character references only: any Tally reads it
    return ElementTree.fromstring(body), count, warnings


def vouchers(root: Element) -> list[Element]:
    return [m.find("VOUCHER") for m in root.iter("TALLYMESSAGE")]  # type: ignore[misc]


def entries(v: Element) -> list[tuple[str, str, Decimal, list[tuple[str, str, Decimal]]]]:
    return [
        (
            e.findtext("LEDGERNAME", ""),
            e.findtext("ISDEEMEDPOSITIVE", ""),
            Decimal(e.findtext("AMOUNT", "0")),
            [
                (
                    b.findtext("NAME", ""),
                    b.findtext("BILLTYPE", ""),
                    Decimal(b.findtext("AMOUNT", "0")),
                )
                for b in e.findall("BILLALLOCATIONS.LIST")
            ],
        )
        for e in v.findall("ALLLEDGERENTRIES.LIST")
    ]


def credit_note(m: Money, bill: dict[str, Any]) -> dict[str, Any]:
    r = APIClient().post(
        f"/api/v1/documents/{bill['id']}/credit-notes",
        {"doc_date": "2026-10-30", "lines": [{**RCC, "quantity": "1"}]},
        format="json",
        **m.h(IDEMPOTENCY_KEY=str(uuid.uuid4())),
    )
    assert r.status_code == 201, r.content
    note = r.json()
    r = APIClient().post(
        f"/api/v1/documents/{note['id']}/issue",
        {},
        format="json",
        **m.h(IF_MATCH='"v1"', IDEMPOTENCY_KEY=str(uuid.uuid4())),
    )
    assert r.status_code == 200, r.content
    return dict(r.json())


def test_sales_credit_note_and_receipt_balance_with_tallys_signs(m: Money) -> None:
    bill = m.invoice()  # 3,41,020 with 5 % retention and 1 % TDS: client pays 3,23,680
    note = credit_note(m, bill)
    pay = m.pay("400000.00", [{"document_id": bill["id"], "amount": "300000.00"}])
    assert pay.status_code == 201, pay.content
    root, count, warnings = build(m)
    assert root.findtext("HEADER/TALLYREQUEST") == "Import Data"
    assert root.findtext("BODY/IMPORTDATA/REQUESTDESC/REPORTNAME") == "Vouchers"
    sale, cn, receipt = vouchers(root)
    assert count == 3
    for v in (sale, cn, receipt):
        assert sum(a for _, _, a, _ in entries(v)) == 0  # every voucher balances
        assert v.get("ACTION") == "Create"

    assert (sale.get("VCHTYPE"), sale.get("REMOTEID")) == ("Sales", bill["id"])
    assert (sale.findtext("DATE"), sale.findtext("VOUCHERNUMBER")) == ("20261019", "INV/0001")
    assert sale.findtext("PARTYLEDGERNAME") == "Skyline Developers"
    assert sale.findtext("PARTYGSTIN") == m.client.gstin
    assert sale.findtext("PLACEOFSUPPLY") == "Kerala"
    assert entries(sale) == [
        ("Skyline Developers", "Yes", Decimal("-323680.00"),
         [("INV/0001", "New Ref", Decimal("-323680.00"))]),
        ("TDS Receivable", "Yes", Decimal("-2890.00"), []),
        ("Retention Receivable", "Yes", Decimal("-14450.00"), []),
        ("Sales", "No", Decimal("289000.00"), []),
        ("Output CGST", "No", Decimal("26010.00"), []),
        ("Output SGST", "No", Decimal("26010.00"), []),
    ]  # fmt: skip

    assert (cn.get("VCHTYPE"), cn.findtext("VOUCHERNUMBER")) == ("Credit Note", note["doc_number"])
    client, sales = entries(cn)[0], entries(cn)[1]
    assert client[:3] == ("Skyline Developers", "No", Decimal(note["totals"]["grand_total"]))
    assert client[3] == [("INV/0001", "Agst Ref", Decimal(note["totals"]["grand_total"]))]
    assert sales[:3] == ("Sales", "Yes", Decimal("-6800.00"))

    assert receipt.get("VCHTYPE") == "Receipt"
    assert receipt.findtext("VOUCHERNUMBER") is None  # Tally numbers its own receipts
    assert entries(receipt) == [
        ("Bank Account", "Yes", Decimal("-400000.00"), []),
        ("Skyline Developers", "No", Decimal("400000.00"),
         [("INV/0001", "Agst Ref", Decimal("300000.00")),
          ("On Account", "On Account", Decimal("100000.00"))]),
    ]  # fmt: skip
    assert "Create these ledgers in Tally before importing" in warnings[-1]
    assert "Skyline Developers" in warnings[-1]


def test_ledger_names_come_from_the_settings(m: Money) -> None:
    r = APIClient().get("/api/v1/tenant/tally-settings", **m.h())
    assert (r.status_code, r.json()["sales_ledger"], r.json()["version"]) == (200, "Sales", 1)
    r = APIClient().patch(
        "/api/v1/tenant/tally-settings",
        {"sales_ledger": "Works Contract Sales 18%", "bank_ledger": "SBI Current A/c"},
        format="json",
        **m.h(IF_MATCH='"v1"'),
    )
    assert r.status_code == 200, r.content
    m.invoice()
    m.pay("1000.00", mode="UPI")
    root, _, _ = build(m)
    sale, receipt = vouchers(root)
    assert "Works Contract Sales 18%" in [e[0] for e in entries(sale)]
    assert entries(receipt)[0][0] == "SBI Current A/c"
    m.pay("500.00", mode="CASH")
    root, _, _ = build(m)
    assert entries(vouchers(root)[-1])[0][0] == "Cash"


def test_ledger_names_are_per_business(m: Money) -> None:
    assert (
        APIClient()
        .get("/api/v1/tenant/tally-settings", **m.h(add_member(m.t, "VIEWER")))
        .status_code
        == 200
    )
    accountant = add_member(m.t, "ACCOUNTANT")
    body = {"sales_ledger": "Sales A"}
    assert APIClient().patch("/api/v1/tenant/tally-settings", body, format="json",
                             **m.h(accountant, IF_MATCH='"v1"')).status_code == 403  # fmt: skip
    assert APIClient().patch("/api/v1/tenant/tally-settings", body, format="json",
                             **m.h(IF_MATCH='"v1"')).status_code == 200  # fmt: skip
    stranger = owner_member(make_tenant("Stranger Co"))
    r = APIClient().get("/api/v1/tenant/tally-settings", **m.h(stranger))
    assert r.json()["sales_ledger"] == "Sales"


def test_cancelled_bills_are_left_out_and_names_survive(m: Money) -> None:
    with tenant_context(m.t.tenant_id, m.t.user_id):
        Party.objects.filter(pk=m.client.pk).update(display_name="ശ്രീ Builders & Co")
    bill = m.invoice()
    r = APIClient().post(
        f"/api/v1/documents/{bill['id']}/cancel",
        {"reason": "Wrong client"},
        format="json",
        **m.h(IF_MATCH=f'"v{bill["version"]}"', IDEMPOTENCY_KEY=str(uuid.uuid4())),
    )
    assert r.status_code == 200, r.content
    kept = m.invoice()
    root, count, warnings = build(m)
    assert count == 1
    [sale] = vouchers(root)
    assert sale.get("REMOTEID") == kept["id"]
    assert sale.findtext("PARTYLEDGERNAME") == "ശ്രീ Builders & Co"  # escaped, read back whole
    assert warnings[0].startswith("1 cancelled bill(s) left out")


def test_through_the_exports_api(m: Money, s3: Any, run: Any) -> None:
    m.invoice()
    bad = APIClient().post(
        "/api/v1/exports", {"kind": "TALLY", "format": "CSV"}, format="json", **m.h()
    )
    assert (bad.status_code, bad.json()["errors"][0]["code"]) == (422, "invalid_format")
    with run():
        r = APIClient().post(
            "/api/v1/exports",
            {
                "kind": "TALLY",
                "format": "XML",
                "params": {"from": "2026-10-01", "to": "2026-10-31"},
            },
            format="json",
            **m.h(),
        )
    assert r.status_code == 202, r.content
    done = APIClient().get(f"/api/v1/exports/{r.json()['id']}", **m.h()).json()
    assert (done["status"], done["file_name"], done["row_count"]) == (
        "READY",
        "tally-vouchers-2026-10-01-to-2026-10-31.xml",
        1,
    )
