"""The main dashboard (W.6), on the statement ledger (tests/reports/test_statement.py):
three October invoices of 341020.00 (taxable 289000.00 each), a credit note of
8024.00 (taxable 6800.00) on 30 Oct, payments of 100000 and 300000 in October
(a voided one and a cancelled bill count nowhere). Here also: an expense on
TOWER bigger than its billing, and a draft.
"""

from decimal import Decimal
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.expenses.models import Expense
from apps.projects.models import Project
from tests.factories import add_member, make_tenant, owner_member
from tests.reports.test_statement import Ledger

pytestmark = pytest.mark.django_db

PERIOD = {"from": "2026-10-01", "to": "2026-11-30"}


class Board(Ledger):
    def __init__(self) -> None:
        super().__init__()
        with tenant_context(self.t.tenant_id, self.t.user_id):
            tower = Project.objects.get(code="TOWER")
            Expense.objects.create(
                project=tower,
                category="SUBCONTRACT",
                expense_date="2026-10-20",
                description="Piling subcontractor",
                taxable_value=Decimal("400000.00"),
                gst_amount=Decimal("72000.00"),
                total_amount=Decimal("472000.00"),
                itc_eligible=True,
                created_by_id=self.t.user_id,
            )
        self.draft = self.create(doc_date="2026-11-01").json()

    def board(self, member: Any = None, **query: str) -> Any:
        return APIClient().get("/api/v1/reports/dashboard", query or PERIOD, **self.h(member))


@pytest.fixture
def b() -> Board:
    return Board()


def test_totals_for_the_period(b: Board) -> None:
    r = b.board()
    assert r.status_code == 200, r.content
    t = r.json()["totals"]
    assert t["billed"] == "1015036.00"  # 3 x 341020 - 8024
    assert t["collected"] == "400000.00"
    assert t["expenses"] == "472000.00"
    # taxable 3 x 289000 - 6800 = 860200, less the expense without its GST (ITC claimable)
    assert t["margin"] == "460200.00"
    summary = APIClient().get("/api/v1/reports/summary", PERIOD, **b.h()).json()["current"]
    assert t["outstanding"] == summary["outstanding"]
    assert Decimal("0") < Decimal(t["overdue"]) <= Decimal(t["outstanding"])
    before = r.json()["previous"]  # 2 months before 1 Oct: nothing yet
    assert r.json()["previous_period"] == {"from": "2026-08-01", "to": "2026-09-30"}
    assert (before["billed"], before["collected"], before["margin"]) == ("0.00", "0.00", "0.00")


def test_twelve_months_of_billed_and_collected(b: Board) -> None:
    months = b.board().json()["months"]
    assert months[0]["month"] == "2025-12-01"
    assert months[-1]["month"] == "2026-11-01"
    assert len(months) == 12
    october = next(m for m in months if m["month"] == "2026-10-01")
    assert (october["billed"], october["collected"]) == ("1015036.00", "400000.00")
    assert months[0] == {"month": "2025-12-01", "billed": "0.00", "collected": "0.00"}


def test_overdue_bills_oldest_first(b: Board) -> None:
    overdue = b.board().json()["overdue"]
    assert overdue["count"] == len(overdue["results"]) >= 1
    numbers = {row["doc_number"] for row in overdue["results"]}
    assert numbers <= {b.inv1["doc_number"], b.inv2["doc_number"], b.inv3["doc_number"]}
    for row in overdue["results"]:
        assert row["days_overdue"] > 0
        assert Decimal(row["outstanding"]) > 0
        assert row["party_name"] == "Skyline Developers"
        assert row["last_reminder_at"] is None
        assert row["party_has_email"] is False  # no address: the page says so


def test_projects_losing_money_and_drafts(b: Board) -> None:
    data = b.board().json()
    assert [(p["code"], p["margin"]) for p in data["losing_projects"]] == [
        ("TOWER", "-111000.00")  # billed taxable 289000 - cost 400000
    ]
    assert data["drafts"]["count"] == 1
    assert data["drafts"]["results"][0]["id"] == b.draft["id"]
    assert data["drafts"]["results"][0]["party_name"] == "Skyline Developers"


def test_book_filter(b: Board) -> None:
    gst = b.board(**PERIOD, book="GST").json()["totals"]
    non_gst = b.board(**PERIOD, book="NON_GST").json()["totals"]
    assert gst["billed"] == "1015036.00"  # every bill here is a tax invoice
    assert non_gst["billed"] == "0.00"


def test_who_may_see_it(b: Board) -> None:
    assert b.board(add_member(b.t, "VIEWER")).status_code == 200
    assert b.board(add_member(b.t, "SITE_ENGINEER")).status_code == 403


def test_another_tenant_sees_only_its_own(b: Board) -> None:
    stranger = owner_member(make_tenant("Other Builder"))
    data = b.board(stranger).json()
    assert data["totals"]["billed"] == "0.00"
    assert data["overdue"] == {"count": 0, "results": []}
    assert data["drafts"]["count"] == 0
    assert data["losing_projects"] == []
