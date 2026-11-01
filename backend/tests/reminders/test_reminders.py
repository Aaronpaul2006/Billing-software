"""Payment reminders (W.2).

One invoice: issued 19 Oct 2026, due 18 Nov 2026, 3,23,680.00 to pay (the
default RA line on VILLA-1, less retention and TDS).
"""

import uuid
from datetime import date
from typing import Any
from unittest import mock

import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.parties.models import Party
from apps.reminders import services
from apps.reminders.models import PaymentReminder
from tests.factories import add_member
from tests.payments.test_payments import Money

pytestmark = pytest.mark.django_db


class Owed(Money):
    def __init__(self) -> None:
        super().__init__()
        self.set_party(email="accounts@skyline.in")
        self.bill = self.invoice(due_date="2026-11-18")

    def set_party(self, **fields: Any) -> None:
        with tenant_context(self.t.tenant_id, self.t.user_id):
            Party.objects.filter(pk=self.client.pk).update(**fields)

    def run(self, day: str) -> int:
        return services.send_due_for_tenant(self.t.tenant_id, date.fromisoformat(day))

    def stages(self) -> list[str]:
        with tenant_context(self.t.tenant_id, self.t.user_id):
            return list(
                PaymentReminder.objects.filter(document_id=self.bill["id"])
                .order_by("sent_at")
                .values_list("stage", flat=True)
            )

    def cancel(self, doc: dict[str, Any]) -> None:
        r = APIClient().post(
            f"/api/v1/documents/{doc['id']}/cancel",
            {"reason": "raised twice"},
            format="json",
            **self.h(IF_MATCH=f'"v{doc["version"]}"', IDEMPOTENCY_KEY=str(uuid.uuid4())),
        )
        assert r.status_code == 200, r.content

    def send_now(self, member: Any = None, doc_id: str | None = None) -> Any:
        return APIClient().post(
            f"/api/v1/documents/{doc_id or self.bill['id']}/reminders",
            {},
            format="json",
            **self.h(member, IDEMPOTENCY_KEY=str(uuid.uuid4())),
        )


@pytest.fixture
def w() -> Owed:
    return Owed()


@pytest.mark.parametrize(
    ("due", "today", "stage"),
    [
        ("2026-11-18", "2026-11-14", None),
        ("2026-11-18", "2026-11-15", "BEFORE_DUE"),
        ("2026-11-18", "2026-11-17", "BEFORE_DUE"),
        ("2026-11-18", "2026-11-18", "ON_DUE"),
        ("2026-11-18", "2026-11-24", "ON_DUE"),
        ("2026-11-18", "2026-11-25", "OVERDUE_7"),
        ("2026-11-18", "2026-12-03", "OVERDUE_15"),
        ("2026-11-18", "2026-12-18", "OVERDUE_30"),
        ("2026-11-18", "2027-06-01", "OVERDUE_30"),
    ],
)
def test_stage_for(due: str, today: str, stage: str | None) -> None:
    assert services.stage_for(date.fromisoformat(due), date.fromisoformat(today)) == stage


def test_the_schedule_once_each_and_no_burst_after_a_gap(w: Owed) -> None:
    assert w.run("2026-11-14") == 0
    assert w.run("2026-11-15") == 1
    assert w.run("2026-11-15") == 0  # the same day again: nothing twice
    assert w.run("2026-11-16") == 0  # still the same stage
    assert w.run("2026-11-18") == 1
    # The job did not run for a month: only the latest stage goes out.
    assert w.run("2026-12-20") == 1
    assert w.run("2026-12-21") == 0
    assert w.stages() == ["BEFORE_DUE", "ON_DUE", "OVERDUE_30"]
    first, _, last = mail.outbox
    assert first.to == ["accounts@skyline.in"]
    assert first.subject == "Payment reminder: Tax Invoice INV/0001 from Nair Constructions"
    assert "is due on 18 Nov 2026" in first.body
    assert "₹3,23,680.00 of it is still unpaid" in first.body
    assert last.subject == "Overdue: Tax Invoice INV/0001 from Nair Constructions"
    assert "was due on 18 Nov 2026, 32 days ago" in last.body


@pytest.mark.parametrize("case", ["paid", "switched_off", "no_email", "no_due_date", "cancelled"])
def test_who_gets_nothing(w: Owed, case: str) -> None:
    if case == "paid":
        r = w.pay("323680.00", allocations=[{"document_id": w.bill["id"], "amount": "323680.00"}])
        assert r.status_code == 201, r.content
    elif case == "switched_off":
        w.set_party(reminders_enabled=False)
    elif case == "no_email":
        w.set_party(email=None)
    elif case == "no_due_date":
        w.cancel(w.bill)
        w.bill = w.invoice()  # the only open bill now has no due date
    else:
        w.cancel(w.bill)
    assert w.run("2026-11-25") == 0
    assert mail.outbox == []


def test_the_daily_job_visits_every_active_tenant(w: Owed) -> None:
    other = Owed()  # a second company with its own bill
    assert services.send_due_reminders(today=date(2026, 11, 18)) == 2
    assert (
        sorted(m.subject for m in mail.outbox)
        == ["Payment reminder: Tax Invoice INV/0001 from Nair Constructions"] * 2
    )
    assert w.stages() == ["ON_DUE"]
    assert other.stages() == ["ON_DUE"]


def test_a_mail_server_failure_logs_nothing_and_is_tried_again(w: Owed) -> None:
    with mock.patch.object(services, "send_mail", side_effect=OSError("connection refused")):
        assert w.run("2026-11-18") == 0
    assert w.stages() == []
    assert w.run("2026-11-18") == 1


def test_send_now_from_the_bill(w: Owed) -> None:
    r = w.send_now()
    assert r.status_code == 201, r.content
    body = r.json()
    assert (body["stage"], body["sent_to"], body["amount_due"]) == (
        "MANUAL",
        "accounts@skyline.in",
        "323680.00",
    )
    assert body["sent_by_name"]
    assert len(mail.outbox) == 1
    again = w.send_now()
    assert (again.status_code, again.json()["code"]) == (409, "reminded_recently")
    w.run("2026-11-18")  # the automatic ones go out regardless
    listed = APIClient().get(f"/api/v1/documents/{w.bill['id']}/reminders", **w.h()).json()
    assert [x["stage"] for x in listed["results"]] == ["ON_DUE", "MANUAL"]  # newest first
    assert listed["results"][0]["sent_by_name"] is None


def test_send_now_is_refused_when_it_cannot_help(w: Owed) -> None:
    viewer = add_member(w.t, "VIEWER")
    assert w.send_now(viewer).status_code == 403
    engineer = add_member(w.t, "SITE_ENGINEER")
    assert w.send_now(engineer).status_code == 403
    draft = w.create().json()
    r = w.send_now(doc_id=draft["id"])
    assert (r.status_code, r.json()["code"]) == (409, "not_receivable")
    w.set_party(email=None)
    r = w.send_now()
    assert (r.status_code, r.json()["errors"][0]["field"]) == (422, "party.email")
    w.set_party(email="accounts@skyline.in")
    w.pay("323680.00", allocations=[{"document_id": w.bill["id"], "amount": "323680.00"}])
    r = w.send_now()
    assert (r.status_code, r.json()["code"]) == (409, "nothing_due")
    with mock.patch.object(services, "send_mail", side_effect=OSError("down")):
        w.bill = w.invoice(due_date="2026-11-18")
        r = w.send_now()
    assert (r.status_code, r.json()["code"]) == (503, "email_unavailable")
    assert w.stages() == []  # nothing logged when nothing was sent
    assert (
        APIClient().get(f"/api/v1/documents/{uuid.uuid4()}/reminders", **w.h()).status_code == 404
    )


def test_party_switch_is_saved(w: Owed) -> None:
    r = APIClient().patch(
        f"/api/v1/parties/{w.client.pk}",
        {"reminders_enabled": False},
        format="json",
        **w.h(IF_MATCH='"v1"'),
    )
    assert r.status_code == 200, r.content
    assert r.json()["reminders_enabled"] is False
