"""Retention releases (Phase 3.3).

Each default invoice (42.5 cum RCC @ 6800, VILLA-1 with 5 % retention) holds
back 14450.00 of retention and asks 323680.00 now; two of them hold 28900.00.
"""

import uuid
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.errors import Invalid
from apps.core.tenancy import tenant_context
from apps.parties.models import Party
from tests.factories import add_member

from .test_credit_notes import Credits
from .test_payments import problem

pytestmark = pytest.mark.django_db


class Held(Credits):
    def __init__(self) -> None:
        super().__init__()
        self.inv1, self.inv2 = self.invoice(), self.invoice()

    def release(self, amount: Any = "20000.00", member: Any = None, **kw: Any) -> Any:
        return APIClient().post(
            "/api/v1/retention-releases",
            {
                "project_id": str(self.project.pk),
                "release_date": "2026-11-05",
                "amount": amount,
                **kw,
            },
            format="json",
            **self.h(member, IDEMPOTENCY_KEY=str(uuid.uuid4())),
        )

    def held(self) -> dict[str, Any]:
        r = APIClient().get(f"/api/v1/projects/{self.project.pk}/retention", **self.h())
        assert r.status_code == 200, r.content
        return dict(r.json())

    def get(self, release_id: str) -> dict[str, Any]:
        return dict(APIClient().get(f"/api/v1/retention-releases/{release_id}", **self.h()).json())

    def cancel(self, release: dict[str, Any], version: int | None = None) -> Any:
        v = release["version"] if version is None else version
        return APIClient().post(
            f"/api/v1/retention-releases/{release['id']}/cancel",
            {"reason": "client withdrew the letter"},
            format="json",
            **self.h(IF_MATCH=f'"v{v}"', IDEMPOTENCY_KEY=str(uuid.uuid4())),
        )


@pytest.fixture
def h() -> Held:
    return Held()


def test_release_within_the_retention_held(h: Held) -> None:
    assert h.held()["GST"] == {"deducted": "28900.00", "released": "0.00", "available": "28900.00"}
    assert h.held()["NON_GST"]["available"] == "0.00"
    r = h.release(reference="SKY/RET/12", due_date="2026-11-20")
    assert r.status_code == 201, r.content
    body = r.json()
    assert (body["book"], body["status"], body["amount"], body["outstanding"]) == (
        "GST",
        "RELEASED",
        "20000.00",
        "20000.00",
    )
    assert (body["party_id"], body["allocations"], body["version"]) == (str(h.client.pk), [], 1)
    assert h.held()["GST"] == {
        "deducted": "28900.00",
        "released": "20000.00",
        "available": "8900.00",
    }
    assert problem(h.release("8900.01")) == (422, "exceeds_retention_held")
    assert h.release("8900.00").status_code == 201
    assert problem(h.release("1.00")) == (422, "nothing_to_release")
    assert problem(h.release("1.00", book="NON_GST")) == (422, "nothing_to_release")


def test_collect_a_release_with_payments(h: Held) -> None:
    rel = h.release().json()
    paid = h.pay("5000.00", [{"retention_release_id": rel["id"], "amount": "5000.00"}])
    assert paid.status_code == 201, paid.content
    [allocation] = paid.json()["allocations"]
    assert (
        allocation["retention_release_id"],
        allocation["document_id"],
        allocation["doc_number"],
    ) == (
        rel["id"],
        None,
        None,
    )
    assert (h.get(rel["id"])["amount_settled"], h.get(rel["id"])["outstanding"]) == (
        "5000.00",
        "15000.00",
    )
    big = h.pay("20000.00").json()
    assert problem(
        h.allocate(big["id"], [{"retention_release_id": rel["id"], "amount": "15000.01"}])
    ) == (
        422,
        "allocation_exceeds_outstanding",
    )
    assert problem(
        h.allocate(
            big["id"],
            [
                {"retention_release_id": rel["id"], "amount": "1.00"},
                {"retention_release_id": rel["id"], "amount": "1.00"},
            ],
        )
    ) == (
        422,
        "duplicate",
    )
    r = h.allocate(
        big["id"],
        [
            {"retention_release_id": rel["id"], "amount": "15000.00"},
            {"document_id": h.inv1["id"], "amount": "5000.00"},
        ],
    )
    assert r.status_code == 200, r.content
    assert h.get(rel["id"])["outstanding"] == "0.00"
    assert len(h.get(rel["id"])["allocations"]) == 2


def test_allocation_input_rules(h: Held) -> None:
    rel = h.release().json()
    payment = h.pay("100.00").json()
    both = {"retention_release_id": rel["id"], "document_id": h.inv1["id"], "amount": "1.00"}
    assert problem(h.allocate(payment["id"], [both])) == (422, "one_target")
    assert problem(h.allocate(payment["id"], [{"amount": "1.00"}])) == (422, "one_target")
    note = h.credit_note(h.inv1)
    r = h.apply(note["id"], [{"retention_release_id": rel["id"], "amount": "1.00"}])
    assert problem(r) == (422, "not_allowed")  # credit notes do not settle releases
    with tenant_context(h.t.tenant_id, h.t.user_id):
        other = Party.objects.create(
            display_name="Other client", gst_treatment="UNREGISTERED", created_by_id=h.t.user_id
        )
    stranger = h.pay("100.00", party_id=str(other.pk)).json()
    assert problem(
        h.allocate(stranger["id"], [{"retention_release_id": rel["id"], "amount": "1.00"}])
    ) == (
        422,
        "party_mismatch",
    )


def test_cancel_a_release(h: Held) -> None:
    rel = h.release().json()
    paid = h.pay("5000.00", [{"retention_release_id": rel["id"], "amount": "5000.00"}]).json()
    assert problem(h.cancel(rel)) == (409, "release_settled")
    APIClient().delete(f"/api/v1/allocations/{paid['allocations'][0]['id']}", **h.h())
    assert h.get(rel["id"])["amount_settled"] == "0.00"
    assert problem(h.cancel(rel, version=7)) == (412, "stale_version")
    cancelled = h.cancel(rel)
    assert cancelled.status_code == 200, cancelled.content
    body = cancelled.json()
    assert (body["status"], body["outstanding"], body["cancel_reason"], body["version"]) == (
        "CANCELLED",
        "0.00",
        "client withdrew the letter",
        2,
    )
    assert problem(h.cancel(body)) == (409, "release_cancelled")
    assert problem(
        h.allocate(paid["id"], [{"retention_release_id": rel["id"], "amount": "1.00"}])
    ) == (
        422,
        "release_cancelled",
    )
    assert h.held()["GST"]["available"] == "28900.00"  # cancelled releases give it back


def test_bills_whose_retention_was_released_cannot_be_cancelled(h: Held) -> None:
    rel = h.release().json()  # 20000 of 28900: either invoice's 14450 is needed
    cancel = APIClient().post(
        f"/api/v1/documents/{h.inv1['id']}/cancel",
        {"reason": "wrong rate"},
        format="json",
        **h.h(IF_MATCH=f'"v{h.inv1["version"]}"', IDEMPOTENCY_KEY=str(uuid.uuid4())),
    )
    assert problem(cancel) == (409, "retention_released")
    h.cancel(rel)
    cancel = APIClient().post(
        f"/api/v1/documents/{h.inv1['id']}/cancel",
        {"reason": "wrong rate"},
        format="json",
        **h.h(IF_MATCH=f'"v{h.inv1["version"]}"', IDEMPOTENCY_KEY=str(uuid.uuid4())),
    )
    assert cancel.status_code == 200, cancel.content
    assert h.held()["GST"]["deducted"] == "14450.00"


def test_receivables_and_reports_include_releases(h: Held) -> None:
    rel = h.release().json()
    h.pay(
        "5000.00",
        [{"retention_release_id": rel["id"], "amount": "5000.00"}],
        payment_date="2026-11-06",
    )
    api, nov = APIClient(), {"from": "2026-11-01", "to": "2026-11-30"}
    [row] = api.get("/api/v1/reports/receivables", **h.h()).json()["results"]
    assert (row["document_count"], row["total"]) == (3, "662360.00")  # 2 x 323680 + 15000
    [project] = api.get("/api/v1/reports/projects", **h.h()).json()["results"]
    assert (project["retention_held"], project["retention_released"], project["outstanding"]) == (
        "8900.00",
        "20000.00",
        "662360.00",
    )
    summary = api.get("/api/v1/reports/summary", {**nov, "book": "GST"}, **h.h()).json()["current"]
    assert (summary["billed"], summary["collected"], summary["outstanding"]) == (
        "0.00",
        "5000.00",
        "662360.00",  # a release is not billing; its payment is collection
    )
    non_gst = api.get("/api/v1/reports/summary", {**nov, "book": "NON_GST"}, **h.h()).json()
    assert non_gst["current"]["collected"] == "0.00"


def test_list_validation_and_roles(h: Held) -> None:
    h.release("1000.00")
    h.cancel(h.release("2000.00").json())
    api = APIClient()
    rows = api.get("/api/v1/retention-releases", {"status": "RELEASED"}, **h.h()).json()["results"]
    assert [r["amount"] for r in rows] == ["1000.00"]
    by_project = api.get("/api/v1/retention-releases", {"project_id": str(h.project.pk)}, **h.h())
    assert len(by_project.json()["results"]) == 2
    assert problem(h.release(due_date="2026-11-01")) == (422, "invalid_dates")
    assert problem(h.release(project_id=str(uuid.uuid4()))) == (422, "not_found")
    assert problem(h.release(amount=20000)) == (422, "not_a_string")
    assert problem(h.release(member=add_member(h.t, "SITE_ENGINEER"))) == (403, "permission_denied")
    viewer = add_member(h.t, "VIEWER")
    assert api.get("/api/v1/retention-releases", **h.h(viewer)).status_code == 200
    assert problem(h.release(member=viewer)) == (403, "permission_denied")


@pytest.mark.parametrize(
    ("message", "code"),
    [
        (
            "new row violates check constraint retention_releases_amount_settled_check",
            "allocation_exceeds_outstanding",
        ),
        ("only open retention releases can be settled", "release_cancelled"),
    ],
)
def test_database_rejections_map_to_api_codes(message: str, code: str) -> None:
    from django.db import DatabaseError

    from apps.payments.services import _db_error_to_problem

    mapped = _db_error_to_problem(DatabaseError(message), "allocations[0].amount")
    assert isinstance(mapped, Invalid)
    assert mapped.code == code
