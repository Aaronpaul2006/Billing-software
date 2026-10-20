"""Issue, cancel, accept / decline, convert, credit & debit notes (Phase 1.6)."""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.core.tenancy import tenant_context
from apps.documents.models import Document
from apps.parties.models import Party
from apps.projects.models import Project
from apps.tenants.models import DocumentSeries
from tests.factories import add_member

from .test_drafts import RCC, World

pytestmark = pytest.mark.django_db


@pytest.fixture
def w() -> World:
    return World()


def series(w: World, doc_type: str = "TAX_INVOICE", prefix: str = "INV/") -> DocumentSeries:
    with tenant_context(w.t.tenant_id, w.t.user_id):
        s: DocumentSeries = DocumentSeries.objects.create(
            gst_registration_id=w.t.registration_id,
            doc_type=doc_type,
            fy_start_year=2026,
            prefix=prefix,
        )
    return s


def act(
    w: World,
    doc: dict[str, Any],
    action: str,
    version: int | None = None,
    body: dict[str, Any] | None = None,
    member: Any = None,
    key: str | None = None,
) -> Any:
    v = doc["version"] if version is None else version
    headers = w.h(member, IF_MATCH=f'"v{v}"', IDEMPOTENCY_KEY=key or str(uuid.uuid4()))
    return APIClient().post(
        f"/api/v1/documents/{doc['id']}/{action}", body or {}, format="json", **headers
    )


def problem(r: Any) -> tuple[int, str]:
    b = r.json()
    return r.status_code, (b["errors"][0]["code"] if b["code"] == "validation_error" else b["code"])


def next_number(s: DocumentSeries, w: World) -> int:
    with tenant_context(w.t.tenant_id, w.t.user_id):
        return int(DocumentSeries.objects.get(pk=s.pk).next_number)


# --- issue --------------------------------------------------------------------------------


def test_issue_assigns_the_next_number_and_freezes_snapshots(w: World) -> None:
    s = series(w)
    first = act(w, w.create().json(), "issue")
    assert first.status_code == 200, first.content
    body = first.json()
    assert (body["status"], body["doc_number"], body["version"]) == ("ISSUED", "INV/0001", 2)
    assert first["ETag"] == '"v2"'
    assert act(w, w.create().json(), "issue").json()["doc_number"] == "INV/0002"
    assert next_number(s, w) == 3

    with tenant_context(w.t.tenant_id, w.t.user_id):
        Party.objects.filter(pk=w.client.pk).update(display_name="Renamed Developers")
        snapshot = Document.objects.get(pk=body["id"]).party_snapshot
        supplier = Document.objects.get(pk=body["id"]).supplier_snapshot
    assert snapshot["display_name"] == "Skyline Developers"  # frozen at issue
    assert supplier["gstin"]
    assert supplier["state_code"] == "32"


def test_issue_needs_if_match_and_an_idempotency_key(w: World) -> None:
    series(w)
    doc = w.create().json()
    url = f"/api/v1/documents/{doc['id']}/issue"
    no_key = APIClient().post(url, {}, format="json", **w.h(IF_MATCH='"v1"'))
    assert problem(no_key) == (428, "idempotency_key_required")
    no_match = APIClient().post(url, {}, format="json", **w.h(IDEMPOTENCY_KEY=str(uuid.uuid4())))
    assert problem(no_match) == (428, "if_match_required")
    assert problem(act(w, doc, "issue", version=7)) == (412, "stale_version")


def test_retry_with_the_same_key_does_not_consume_a_second_number(w: World) -> None:
    s = series(w)
    doc, key = w.create().json(), str(uuid.uuid4())
    first = act(w, doc, "issue", key=key)
    retry = act(w, doc, "issue", key=key)
    assert retry["Idempotent-Replayed"] == "true"
    assert retry.json()["doc_number"] == first.json()["doc_number"] == "INV/0001"
    assert next_number(s, w) == 2


def test_issuing_needs_a_verified_email(w: World) -> None:
    s = series(w)
    doc = w.create().json()
    User.objects.filter(pk=w.t.user_id).update(email_verified_at=None)
    assert problem(act(w, doc, "issue")) == (403, "email_not_verified")
    assert next_number(s, w) == 1


def test_failed_issues_leave_no_gap(w: World) -> None:
    doc = w.create().json()
    assert problem(act(w, doc, "issue")) == (409, "series_missing")
    empty = w.create(lines=[]).json()
    s = series(w)
    assert problem(act(w, empty, "issue")) == (422, "no_lines")
    assert next_number(s, w) == 1
    assert act(w, doc, "issue").json()["doc_number"] == "INV/0001"


def test_issue_recomputes_with_current_project_settings(w: World) -> None:
    series(w)
    doc = w.create().json()
    assert doc["totals"]["retention"] == "14450.00"
    with tenant_context(w.t.tenant_id, w.t.user_id):
        Project.objects.filter(pk=w.project.pk).update(retention_pct=Decimal("10"))
    issued = act(w, doc, "issue").json()
    assert issued["totals"]["retention"] == "28900.00"


def test_issued_document_cannot_be_issued_again(w: World) -> None:
    series(w)
    issued = act(w, w.create().json(), "issue").json()
    assert problem(act(w, issued, "issue")) == (409, "document_not_draft")


def test_only_issuing_roles_issue(w: World) -> None:
    series(w)
    engineer = add_member(w.t, "SITE_ENGINEER")
    doc = w.create(member=engineer).json()  # engineers draft ...
    assert problem(act(w, doc, "issue", member=engineer)) == (
        403,
        "permission_denied",
    )  # ... not issue
    assert act(w, doc, "issue", member=add_member(w.t, "ACCOUNTANT")).status_code == 200


# --- cancel ---------------------------------------------------------------------------------


def test_cancel_keeps_the_number_used(w: World) -> None:
    series(w)
    issued = act(w, w.create().json(), "issue").json()
    assert problem(act(w, issued, "cancel", body={})) == (422, "required")
    cancelled = act(w, issued, "cancel", body={"reason": "Wrong client"})
    assert cancelled.status_code == 200, cancelled.content
    assert cancelled.json()["status"] == "CANCELLED"
    assert act(w, w.create().json(), "issue").json()["doc_number"] == "INV/0002"
    draft = w.create().json()
    assert problem(act(w, draft, "cancel", body={"reason": "x" * 5})) == (409, "not_cancellable")


# --- quotations, conversion -----------------------------------------------------------------


def test_quotation_accept_decline_and_convert(w: World) -> None:
    series(w, "QUOTATION", "QT/")
    series(w)
    quote = act(w, w.create(doc_type="QUOTATION", valid_until="2026-11-30").json(), "issue").json()
    assert quote["doc_number"] == "QT/0001"
    accepted = act(w, quote, "accept").json()
    assert accepted["status"] == "ACCEPTED"
    assert problem(act(w, accepted, "decline")) == (409, "not_issued")

    converted = act(w, accepted, "convert", body={"to": "TAX_INVOICE", "doc_date": "2026-10-25"})
    assert converted.status_code == 201, converted.content
    invoice = converted.json()
    assert (invoice["doc_type"], invoice["status"], invoice["doc_date"]) == (
        "TAX_INVOICE",
        "DRAFT",
        "2026-10-25",
    )
    assert invoice["totals"]["retention"] == "14450.00"  # deductions apply to invoices
    with tenant_context(w.t.tenant_id, w.t.user_id):
        assert Document.objects.get(pk=invoice["id"]).source_document_id == uuid.UUID(quote["id"])
    assert problem(
        act(w, invoice, "convert", body={"to": "PROFORMA", "doc_date": "2026-10-25"})
    ) == (
        422,
        "not_convertible",
    )


def test_declined_quotation_cannot_be_converted_and_invoices_are_not_quotations(w: World) -> None:
    series(w, "QUOTATION", "QT/")
    series(w)
    quote = act(w, w.create(doc_type="QUOTATION").json(), "issue").json()
    declined = act(w, quote, "decline").json()
    assert problem(
        act(w, declined, "convert", body={"to": "TAX_INVOICE", "doc_date": "2026-10-25"})
    ) == (
        409,
        "not_convertible",
    )
    invoice = act(w, w.create().json(), "issue").json()
    assert problem(act(w, invoice, "accept")) == (409, "not_a_quotation")


# --- credit & debit notes ----------------------------------------------------------------


def test_credit_note_against_an_issued_invoice(w: World) -> None:
    series(w)
    series(w, "CREDIT_NOTE", "CN/")
    invoice = act(w, w.create().json(), "issue").json()

    draft = act(
        w, invoice, "credit-notes", body={"doc_date": "2026-10-30", "notes": "Rate revised"}
    )
    assert draft.status_code == 201, draft.content
    note = draft.json()
    assert (note["doc_type"], note["status"]) == ("CREDIT_NOTE", "DRAFT")
    assert note["totals"]["grand_total"] == invoice["totals"]["grand_total"]  # lines copied
    assert note["totals"]["retention"] == "0.00"  # notes carry no deductions

    edit = APIClient().patch(
        f"/api/v1/documents/{note['id']}",
        {"lines": [{**RCC, "quantity": "1"}]},
        format="json",
        **w.h(IF_MATCH='"v1"'),
    )
    assert edit.status_code == 200
    assert problem(
        APIClient().patch(
            f"/api/v1/documents/{note['id']}",
            {"doc_type": "TAX_INVOICE"},
            format="json",
            **w.h(IF_MATCH='"v2"'),
        )
    ) == (422, "not_allowed")
    issued = act(w, edit.json(), "issue")
    assert issued.status_code == 200, issued.content
    assert issued.json()["doc_number"] == "CN/0001"

    # the invoice cannot be cancelled while a credit note refers to it
    assert problem(act(w, invoice, "cancel", body={"reason": "duplicate"})) == (
        409,
        "has_issued_notes",
    )


def test_credit_notes_cannot_exceed_the_invoice(w: World) -> None:
    series(w)
    series(w, "CREDIT_NOTE", "CN/")
    invoice = act(w, w.create().json(), "issue").json()
    full = act(w, invoice, "credit-notes", body={"doc_date": "2026-10-30"}).json()
    assert act(w, full, "issue").status_code == 200
    extra = act(
        w,
        invoice,
        "credit-notes",
        body={"doc_date": "2026-10-31", "lines": [{**RCC, "quantity": "0.001"}]},
    ).json()
    assert problem(act(w, extra, "issue")) == (422, "credit_exceeds_original")


def test_notes_only_against_issued_tax_invoices(w: World) -> None:
    series(w)
    draft = w.create().json()
    assert problem(act(w, draft, "debit-notes", body={"doc_date": "2026-10-30"})) == (
        409,
        "not_an_issued_invoice",
    )
    invoice = act(w, w.create().json(), "issue").json()
    assert problem(act(w, invoice, "debit-notes", body={"doc_date": "2026-10-01"})) == (
        422,
        "invalid_dates",
    )
    debit = act(
        w,
        invoice,
        "debit-notes",
        body={
            "doc_date": "2026-10-30",
            "lines": [{**RCC, "description": "Extra work", "quantity": "2"}],
        },
    )
    assert debit.status_code == 201
    assert debit.json()["doc_type"] == "DEBIT_NOTE"
