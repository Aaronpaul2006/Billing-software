"""Notifications (Part B): few, sent once, each person's own."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.notifications import services, tasks
from apps.notifications.models import Notification
from apps.parties.models import Party
from apps.payables.models import VendorBill
from tests.factories import Member, add_member
from tests.portal.test_portal import Portal

pytestmark = pytest.mark.django_db


def mine(p: Portal, member: Member | None = None, **query: Any) -> Any:
    return APIClient().get("/api/v1/notifications", query, **p.h(member)).json()["results"]


def unread(p: Portal, member: Member | None = None) -> int:
    r = APIClient().get("/api/v1/notifications/unread-count", **p.h(member))
    return int(r.json()["count"])


@pytest.fixture
def p() -> Portal:
    return Portal()


def test_a_client_accepting_a_quotation_tells_those_who_bill(
    p: Portal, django_capture_on_commit_callbacks: Any
) -> None:
    accountant = add_member(p.t, "ACCOUNTANT")
    engineer = add_member(p.t, "SITE_ENGINEER")
    with django_capture_on_commit_callbacks(execute=True):
        assert p.answer(p.quote, "accept").status_code == 200
    got = mine(p)
    assert len(got) == 1
    n = got[0]
    assert n["kind"] == "QUOTATION_ACCEPTED"
    assert n["title"] == f"Skyline Developers accepted {p.quote['doc_number']}"
    assert n["link"] == f"/documents/{p.quote['id']}"
    assert n["read_at"] is None
    assert len(mine(p, accountant)) == 1
    assert mine(p, engineer) == []  # site engineers do not bill

    # read one, then all
    assert unread(p) == 1
    r = APIClient().post(f"/api/v1/notifications/{n['id']}/read", **p.h())
    assert r.json()["read_at"] is not None
    assert unread(p) == 0
    assert mine(p, unread="true") == []
    r = APIClient().post("/api/v1/notifications/read-all", **p.h(accountant))
    assert r.json()["count"] == 1
    assert unread(p, accountant) == 0


def test_only_ones_own(p: Portal, django_capture_on_commit_callbacks: Any) -> None:
    accountant = add_member(p.t, "ACCOUNTANT")
    with django_capture_on_commit_callbacks(execute=True):
        p.answer(p.quote, "decline")
    owners = mine(p)
    assert owners[0]["kind"] == "QUOTATION_DECLINED"
    # the accountant has their own copy, and cannot reach the owner's
    r = APIClient().post(f"/api/v1/notifications/{owners[0]['id']}/read", **p.h(accountant))
    assert r.status_code == 404
    assert unread(p) == 1
    other = Portal()
    assert mine(other) == []
    r = APIClient().post(f"/api/v1/notifications/{owners[0]['id']}/read", **other.h())
    assert r.status_code == 404


def test_daily_overdue_and_payables_once_a_day(p: Portal) -> None:
    with tenant_context(p.t.tenant_id, p.t.user_id):
        vendor = Party.objects.create(
            display_name="Kerala Steel Traders",
            gst_treatment="UNREGISTERED",
            is_customer=False,
            is_vendor=True,
            created_by_id=p.t.user_id,
        )
        # the Ledger's bills are dated 19 Oct with no due date: overdue from 20 Oct
        today = date(2026, 10, 20)
        VendorBill.objects.create(
            vendor_party=vendor,
            bill_number="KST/9",
            bill_date=today - timedelta(days=10),
            due_date=today + timedelta(days=2),
            category="MATERIAL",
            description="Steel",
            taxable_value=Decimal("1000.00"),
            total_amount=Decimal("1000.00"),
            net_payable=Decimal("1000.00"),
            created_by_id=p.t.user_id,
        )
    sent = services.daily(p.t.tenant_id, today)
    assert sent == 2  # to the owner: bills overdue, payables due
    assert services.daily(p.t.tenant_id, today) == 2  # tried again: nothing new lands
    kinds = sorted(n["kind"] for n in mine(p))
    assert kinds == ["BILLS_OVERDUE", "PAYABLES_DUE"]
    payables = next(n for n in mine(p) if n["kind"] == "PAYABLES_DUE")
    assert payables["title"] == "1 payment to vendors due by 23 Oct"
    assert payables["body"] == "₹1,000.00 to pay."
    assert services.daily(p.t.tenant_id, today + timedelta(days=30)) == 0  # nothing that day


def test_a_member_joining_tells_those_who_manage_members(p: Portal) -> None:
    admin = add_member(p.t, "ADMIN")
    newcomer = add_member(p.t, "ACCOUNTANT")
    assert tasks.member_joined(str(p.t.tenant_id), str(newcomer.user_id)) == 2  # owner, admin
    n = mine(p, admin)[0]
    assert (n["kind"], n["link"]) == ("MEMBER_JOINED", "/settings/members")
    assert n["title"].endswith("joined as accountant")
    assert mine(p, newcomer) == []
    # a client's portal login is not news for the team
    assert tasks.member_joined(str(p.t.tenant_id), str(p.me.user_id)) == 0


def test_the_database_keeps_each_persons_own() -> None:
    p = Portal()
    with tenant_context(p.t.tenant_id, p.t.user_id):
        services.send(p.t.tenant_id, ("OWNER",), kind="BILLS_OVERDUE", title="x", dedupe_key="k")
        assert Notification.objects.count() == 1
    accountant = add_member(p.t, "ACCOUNTANT")
    with tenant_context(p.t.tenant_id, accountant.user_id):
        assert Notification.objects.count() == 0  # not theirs: not even visible
