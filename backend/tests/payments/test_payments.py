"""Payments and allocations (Phase 2.1)."""

import uuid
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.parties.models import Party
from apps.payments.models import Payment
from apps.tenants.models import DocumentSeries
from tests.documents.test_drafts import World
from tests.factories import add_member

pytestmark = pytest.mark.django_db
NET = "323680.00"  # the API design example invoice


class Money(World):
    def __init__(self) -> None:
        super().__init__()
        with tenant_context(self.t.tenant_id, self.t.user_id):
            for doc_type, prefix in (("TAX_INVOICE", "INV/"), ("QUOTATION", "QT/")):
                DocumentSeries.objects.create(
                    gst_registration_id=self.t.registration_id,
                    doc_type=doc_type,
                    fy_start_year=2026,
                    prefix=prefix,
                )

    def invoice(self, **kw: Any) -> dict[str, Any]:
        draft = self.create(**kw).json()
        r = APIClient().post(
            f"/api/v1/documents/{draft['id']}/issue",
            {},
            format="json",
            **self.h(IF_MATCH='"v1"', IDEMPOTENCY_KEY=str(uuid.uuid4())),
        )
        assert r.status_code == 200, r.content
        return dict(r.json())

    def pay(
        self,
        amount: str,
        allocations: list[dict[str, str]] | None = None,
        member: Any = None,
        key: str | None = None,
        **kw: Any,
    ) -> Any:
        body = {
            "party_id": str(self.client.pk),
            "payment_date": "2026-10-25",
            "amount": amount,
            "mode": "BANK_TRANSFER",
            "reference": "UTR SBIN0026102500123",
            **kw,
        }
        if allocations is not None:
            body["allocations"] = allocations
        return APIClient().post(
            "/api/v1/payments",
            body,
            format="json",
            **self.h(member, IDEMPOTENCY_KEY=key or str(uuid.uuid4())),
        )

    def allocate(self, payment_id: str, allocations: list[dict[str, str]]) -> Any:
        return APIClient().post(
            f"/api/v1/payments/{payment_id}/allocations",
            {"allocations": allocations},
            format="json",
            **self.h(IDEMPOTENCY_KEY=str(uuid.uuid4())),
        )

    def totals(self, doc_id: str) -> dict[str, str]:
        return dict(APIClient().get(f"/api/v1/documents/{doc_id}", **self.h()).json()["totals"])


@pytest.fixture
def m() -> Money:
    return Money()


def problem(r: Any) -> tuple[int, str]:
    b = r.json()
    return r.status_code, (b["errors"][0]["code"] if b["code"] == "validation_error" else b["code"])


def test_record_a_payment_and_allocate_it_in_one_request(m: Money) -> None:
    inv = m.invoice()
    r = m.pay("300000.00", [{"document_id": inv["id"], "amount": "300000.00"}])
    assert r.status_code == 201, r.content
    body = r.json()
    assert (body["allocated"], body["unallocated"], body["status"]) == (
        "300000.00",
        "0.00",
        "RECORDED",
    )
    assert body["allocations"][0]["doc_number"] == "INV/0001"
    totals = m.totals(inv["id"])
    assert (totals["amount_settled"], totals["outstanding"]) == ("300000.00", "23680.00")
    partial = APIClient().get("/api/v1/documents", {"payment_state": "PARTIAL"}, **m.h()).json()
    assert [d["id"] for d in partial["results"]] == [inv["id"]]


def test_allocate_the_leftover_later_and_settle_fully(m: Money) -> None:
    inv = m.invoice()
    payment = m.pay("400000.00").json()
    assert payment["unallocated"] == "400000.00"
    r = m.allocate(payment["id"], [{"document_id": inv["id"], "amount": NET}])
    assert r.status_code == 200, r.content
    assert r.json()["unallocated"] == "76320.00"
    assert m.totals(inv["id"])["outstanding"] == "0.00"
    paid = APIClient().get("/api/v1/documents", {"payment_state": "PAID"}, **m.h()).json()
    assert [d["id"] for d in paid["results"]] == [inv["id"]]


def test_allocation_limits(m: Money) -> None:
    inv = m.invoice()
    other = m.invoice()
    payment = m.pay("10000.00").json()
    over_doc = m.allocate(payment["id"], [{"document_id": inv["id"], "amount": "323680.01"}])
    assert problem(over_doc) == (422, "allocation_exceeds_outstanding")
    over_pay = m.allocate(
        payment["id"],
        [
            {"document_id": inv["id"], "amount": "6000.00"},
            {"document_id": other["id"], "amount": "4000.01"},
        ],
    )
    assert problem(over_pay) == (422, "allocation_exceeds_payment")
    assert m.totals(inv["id"])["amount_settled"] == "0.00"  # all or nothing
    twice = m.allocate(
        payment["id"],
        [
            {"document_id": inv["id"], "amount": "1.00"},
            {"document_id": inv["id"], "amount": "1.00"},
        ],
    )
    assert problem(twice) == (422, "duplicate")
    assert (
        m.allocate(payment["id"], [{"document_id": inv["id"], "amount": "1.00"}]).status_code == 200
    )
    again = m.allocate(payment["id"], [{"document_id": inv["id"], "amount": "1.00"}])
    assert problem(again) == (409, "already_allocated")


def test_only_issued_invoices_of_the_same_party_are_settled(m: Money) -> None:
    draft = m.create().json()
    quote = m.invoice(doc_type="QUOTATION")
    payment = m.pay("1000.00").json()
    for doc in (draft, quote):
        r = m.allocate(payment["id"], [{"document_id": doc["id"], "amount": "1.00"}])
        assert problem(r) == (422, "document_not_settleable")
    with tenant_context(m.t.tenant_id, m.t.user_id):
        stranger = Party.objects.create(
            display_name="Other client", gst_treatment="UNREGISTERED", created_by_id=m.t.user_id
        )
    foreign = m.pay("1000.00", party_id=str(stranger.pk)).json()
    inv = m.invoice()
    assert problem(m.allocate(foreign["id"], [{"document_id": inv["id"], "amount": "1.00"}])) == (
        422,
        "party_mismatch",
    )
    assert problem(
        m.allocate(payment["id"], [{"document_id": str(uuid.uuid4()), "amount": "1.00"}])
    ) == (
        422,
        "not_found",
    )


def test_unwind_an_allocation(m: Money) -> None:
    inv = m.invoice()
    payment = m.pay("5000.00", [{"document_id": inv["id"], "amount": "5000.00"}]).json()
    allocation = payment["allocations"][0]["id"]
    assert APIClient().delete(f"/api/v1/allocations/{allocation}", **m.h()).status_code == 204
    assert m.totals(inv["id"])["amount_settled"] == "0.00"
    detail = APIClient().get(f"/api/v1/payments/{payment['id']}", **m.h()).json()
    assert (detail["allocations"], detail["unallocated"]) == ([], "5000.00")


def test_void_unwinds_allocations_and_cannot_repeat(m: Money) -> None:
    inv = m.invoice()
    payment = m.pay("5000.00", [{"document_id": inv["id"], "amount": "5000.00"}]).json()
    # a settled invoice cannot be cancelled (Phase 1.6) ...
    cancel = APIClient().post(
        f"/api/v1/documents/{inv['id']}/cancel",
        {"reason": "duplicate"},
        format="json",
        **m.h(IF_MATCH=f'"v{inv["version"]}"'),
    )
    assert problem(cancel) == (409, "document_settled")
    url = f"/api/v1/payments/{payment['id']}/void"
    assert problem(APIClient().post(url, {}, format="json", **m.h(IF_MATCH='"v1"'))) == (
        422,
        "required",
    )
    voided = APIClient().post(
        url, {"reason": "Cheque bounced"}, format="json", **m.h(IF_MATCH='"v1"')
    )
    assert voided.status_code == 200, voided.content
    body = voided.json()
    assert (body["status"], body["allocations"], body["unallocated"]) == ("VOIDED", [], "0.00")
    assert m.totals(inv["id"])["amount_settled"] == "0.00"
    again = APIClient().post(url, {"reason": "again"}, format="json", **m.h(IF_MATCH='"v2"'))
    assert problem(again) == (409, "payment_voided")
    assert problem(m.allocate(payment["id"], [{"document_id": inv["id"], "amount": "1.00"}])) == (
        409,
        "payment_voided",
    )
    # ... and is cancellable again once nothing is settled
    cancel = APIClient().post(
        f"/api/v1/documents/{inv['id']}/cancel",
        {"reason": "duplicate"},
        format="json",
        **m.h(IF_MATCH=f'"v{inv["version"]}"'),
    )
    assert cancel.status_code == 200


def test_payment_rules_and_roles(m: Money) -> None:
    assert problem(m.pay(5000)) == (422, "not_a_string")  # type: ignore[arg-type]
    assert problem(m.pay("0.00")) == (422, "min_value")
    other_project = m.make_project("P-OTHER", "32")
    with tenant_context(m.t.tenant_id, m.t.user_id):
        stranger = Party.objects.create(
            display_name="X", gst_treatment="UNREGISTERED", created_by_id=m.t.user_id
        )
    assert problem(m.pay("1.00", party_id=str(stranger.pk), project_id=str(other_project.pk))) == (
        422,
        "party_mismatch",
    )
    assert problem(m.pay("1.00", member=add_member(m.t, "SITE_ENGINEER"))) == (
        403,
        "permission_denied",
    )
    viewer = add_member(m.t, "VIEWER")
    assert APIClient().get("/api/v1/payments", **m.h(viewer)).status_code == 200


def test_recording_is_idempotent_and_payments_are_never_deleted(m: Money) -> None:
    key = str(uuid.uuid4())
    first, retry = m.pay("100.00", key=key), m.pay("100.00", key=key)
    assert retry["Idempotent-Replayed"] == "true"
    assert first.json()["id"] == retry.json()["id"]
    with tenant_context(m.t.tenant_id, m.t.user_id):
        assert Payment.objects.count() == 1
    assert APIClient().delete(f"/api/v1/payments/{first.json()['id']}", **m.h()).status_code == 405


def test_list_filters(m: Money) -> None:
    m.pay("100.00", mode="UPI")
    m.pay("200.00", payment_date="2026-11-02")
    api = APIClient()
    assert [
        p["amount"] for p in api.get("/api/v1/payments", {"mode": "UPI"}, **m.h()).json()["results"]
    ] == ["100.00"]
    later = api.get("/api/v1/payments", {"payment_date_from": "2026-11-01"}, **m.h()).json()[
        "results"
    ]
    assert [p["amount"] for p in later] == ["200.00"]


@pytest.mark.parametrize(
    ("message", "code"),
    [
        (
            'new row for relation "documents" violates check constraint "documents_amount_settled_check"',
            "allocation_exceeds_outstanding",
        ),
        ("allocation exceeds the unallocated amount of its source", "allocation_exceeds_payment"),
        (
            "only issued invoices, bills of supply and debit notes can be settled",
            "document_not_settleable",
        ),
        (
            "allocation source must be a recorded payment / issued credit note of the same party",
            "party_mismatch",
        ),
    ],
)
def test_database_rejections_map_to_api_codes(message: str, code: str) -> None:
    from django.db import DatabaseError

    from apps.core.errors import Invalid
    from apps.payments.services import _db_error_to_problem

    mapped = _db_error_to_problem(DatabaseError(message), "allocations[0].amount")
    assert isinstance(mapped, Invalid)
    assert (mapped.code, mapped.field) == (code, "allocations[0].amount")


def test_duplicate_allocation_race_maps_to_conflict() -> None:
    from django.db import IntegrityError

    from apps.core.errors import Conflict
    from apps.payments.services import _db_error_to_problem

    mapped = _db_error_to_problem(
        IntegrityError('duplicate key value violates unique constraint "allocations_payment_uq"'),
        "x",
    )
    assert isinstance(mapped, Conflict)
    assert mapped.code == "already_allocated"
