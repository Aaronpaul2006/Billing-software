"""Statement of account (W.1), worked by hand.

Each default invoice: 42.5 cum RCC @ 6800 = 289000.00 + 18 % GST = 341020.00;
retention 5 % = 14450.00 and TDS 1 % = 2890.00 are deducted, so the client
owes 323680.00 for it. On TOWER (mobilisation advance 1,00,000, recovered at
10 % of taxable) the bill also adjusts 28900.00 of the advance: its net is
294780.00, but it still adds 323680.00 to the statement, because the advance
was a payment the statement already credits.
"""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from rest_framework.test import APIClient

from tests.factories import add_member
from tests.payments.test_retention import Held

pytestmark = pytest.mark.django_db

BILL = Decimal("323680.00")


class Ledger(Held):
    """Two VILLA-1 invoices (19 Oct, from Held) and the rest of the client's month."""

    def __init__(self) -> None:
        super().__init__()
        self.advance = self.pay("100000.00", payment_date="2026-10-01", reference="ADV-1")
        assert self.advance.status_code == 201, self.advance.content
        tower = self.make_project(
            "TOWER",
            "32",
            mobilisation_advance=Decimal("100000"),
            advance_recovery_pct=Decimal("10"),
        )
        self.inv3 = self.invoice(project_id=str(tower.pk))
        assert self.inv3["totals"]["advance_recovery"] == "28900.00"
        assert self.inv3["totals"]["net_receivable"] == "294780.00"
        paid = self.pay(
            "300000.00",
            allocations=[{"document_id": self.inv1["id"], "amount": "300000.00"}],
        )
        assert paid.status_code == 201, paid.content
        self.note = self.credit_note(self.inv1)  # 30 Oct, 1 cum
        r = self.release("20000.00")  # 5 Nov
        assert r.status_code == 201, r.content
        # Counted nowhere: a cancelled bill and a voided payment.
        cancelled = self.invoice(doc_date="2026-10-20")
        r = APIClient().post(
            f"/api/v1/documents/{cancelled['id']}/cancel",
            {"reason": "wrong client"},
            format="json",
            **self.h(IF_MATCH=f'"v{cancelled["version"]}"', IDEMPOTENCY_KEY=str(uuid.uuid4())),
        )
        assert r.status_code == 200, r.content
        voided = self.pay("5000.00", payment_date="2026-10-26").json()
        r = APIClient().post(
            f"/api/v1/payments/{voided['id']}/void",
            {"reason": "cheque bounced"},
            format="json",
            **self.h(IF_MATCH=f'"v{voided["version"]}"', IDEMPOTENCY_KEY=str(uuid.uuid4())),
        )
        assert r.status_code == 200, r.content

    def note_credit(self) -> Decimal:
        t = self.note["totals"]
        return (
            Decimal(t["grand_total"])
            - Decimal(t["retention"])
            - Decimal(t["income_tax_tds"])
            - Decimal(t["gst_tds"])
        )

    def statement(self, member: Any = None, **query: str) -> Any:
        return APIClient().get(
            f"/api/v1/parties/{self.client.pk}/statement", query, **self.h(member)
        )


@pytest.fixture
def ledger() -> Ledger:
    return Ledger()


def test_the_month_in_order_with_a_running_balance(ledger: Ledger) -> None:
    r = ledger.statement(**{"from": "2026-10-01", "to": "2026-11-30"})
    assert r.status_code == 200, r.content
    s = r.json()
    credit = ledger.note_credit()
    assert credit == Decimal("8024.00")  # a note has no retention or TDS of its own
    rows = [(e["date"], e["kind"], e["debit"], e["credit"], e["balance"]) for e in s["entries"]]
    assert rows == [
        ("2026-10-01", "PAYMENT", "0.00", "100000.00", "-100000.00"),
        ("2026-10-19", "TAX_INVOICE", "323680.00", "0.00", "223680.00"),
        ("2026-10-19", "TAX_INVOICE", "323680.00", "0.00", "547360.00"),
        ("2026-10-19", "TAX_INVOICE", "323680.00", "0.00", "871040.00"),
        ("2026-10-25", "PAYMENT", "0.00", "300000.00", "571040.00"),
        ("2026-10-30", "CREDIT_NOTE", "0.00", "8024.00", "563016.00"),
        ("2026-11-05", "RETENTION_RELEASE", "20000.00", "0.00", "583016.00"),
    ]
    assert s["opening_balance"] == "0.00"
    assert s["total_debit"] == "991040.00"  # 3 x 323680 + 20000
    assert s["total_credit"] == "408024.00"  # 100000 + 300000 + 8024
    assert s["closing_balance"] == "583016.00"
    assert s["party"]["display_name"] == "Skyline Developers"
    words = [e["description"] for e in s["entries"]]
    assert words[0] == "Payment received · Bank transfer · ADV-1"
    assert words[1] == "Tax invoice INV/0001 (less retention 14,450.00 and TDS 2,890.00)"
    assert words[3].endswith("· advance 28,900.00 adjusted")
    assert words[5] == "Credit note CN/0001 · against INV/0001"
    assert s["entries"][1]["document_id"] == ledger.inv1["id"]


def test_opening_balance_carries_what_came_before(ledger: Ledger) -> None:
    s = ledger.statement(**{"from": "2026-10-20", "to": "2026-10-31"}).json()
    assert s["opening_balance"] == "871040.00"  # 3 bills less the advance
    assert [e["kind"] for e in s["entries"]] == ["PAYMENT", "CREDIT_NOTE"]
    assert s["closing_balance"] == "563016.00"  # the release (5 Nov) is after `to`


def test_defaults_roles_and_other_parties(ledger: Ledger) -> None:
    s = ledger.statement().json()  # this financial year to today
    assert s["from"].endswith("-04-01")
    viewer = add_member(ledger.t, "VIEWER")
    assert ledger.statement(viewer).status_code == 200
    engineer = add_member(ledger.t, "SITE_ENGINEER")
    assert ledger.statement(engineer).status_code == 403
    r = APIClient().get(f"/api/v1/parties/{uuid.uuid4()}/statement", **ledger.h())
    assert r.status_code == 404
    bad = ledger.statement(**{"from": "2026-11-01", "to": "2026-10-01"})
    assert (bad.status_code, bad.json()["errors"][0]["field"]) == (422, "from")
