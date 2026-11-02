"""Client portal API (W.5b): a client's people see their own bills, payments,
statement and BOQ progress, and answer quotations; nothing else.

Built on the statement ledger (tests/reports/test_statement.py): Skyline
Developers with three issued invoices, a credit note, a cancelled bill, a
retention release, payments (one voided) and two projects.
"""

import uuid
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.parties.models import Party
from apps.projects.models import Project
from tests.factories import Member, add_client, add_member, make_tenant
from tests.reports.test_statement import Ledger

pytestmark = pytest.mark.django_db


class Portal(Ledger):
    def __init__(self) -> None:
        super().__init__()
        self.me: Member = add_client(self.t, self.client)
        self.quote = self.invoice(doc_type="QUOTATION", valid_until="2027-03-31")
        self.old_quote = self.invoice(doc_type="QUOTATION", valid_until="2026-10-25")
        self.draft = self.create().json()
        with tenant_context(self.t.tenant_id, self.t.user_id):
            self.other = Party.objects.create(
                display_name="Other Client",
                gst_treatment="UNREGISTERED",
                state_code="32",
                created_by_id=self.t.user_id,
            )
            self.other_project = Project.objects.create(
                code="OTHER",
                name="Other site",
                client_party=self.other,
                gst_registration_id=self.t.registration_id,
                site_state_code="32",
                created_by_id=self.t.user_id,
            )
        self.others_bill = self.invoice(
            party_id=str(self.other.pk), project_id=str(self.other_project.pk)
        )

    def portal(
        self, path: str, member: Member | None = None, query: dict[str, str] | None = None
    ) -> Any:
        return APIClient().get(f"/api/v1/portal/{path}", query or {}, **self.h(member or self.me))

    def answer(self, doc: dict[str, Any], action: str, version: int | None = None) -> Any:
        v = doc["version"] if version is None else version
        return APIClient().post(
            f"/api/v1/portal/documents/{doc['id']}/{action}",
            {},
            format="json",
            **self.h(self.me, IF_MATCH=f'"v{v}"'),
        )


@pytest.fixture
def p() -> Portal:
    return Portal()


def code(r: Any) -> str:
    return str(r.json()["code"])


def test_me_names_the_business_and_the_client(p: Portal) -> None:
    r = p.portal("me")
    assert r.status_code == 200, r.content
    assert r.json()["business"]["legal_name"] == "Nair Constructions"
    assert r.json()["client"] == {
        "id": str(p.client.pk),
        "display_name": "Skyline Developers",
        "gstin": p.client.gstin,
    }


def test_documents_are_the_clients_own_issued_ones(p: Portal) -> None:
    r = p.portal("documents")
    assert r.status_code == 200, r.content
    ids = {d["id"] for d in r.json()["results"]}
    assert {p.inv1["id"], p.inv2["id"], p.inv3["id"], p.note["id"], p.quote["id"]} <= ids
    assert p.draft["id"] not in ids
    assert p.others_bill["id"] not in ids
    quotes = p.portal("documents", query={"doc_type": "QUOTATION"}).json()["results"]
    assert {d["id"] for d in quotes} == {p.quote["id"], p.old_quote["id"]}
    row = next(d for d in r.json()["results"] if d["id"] == p.inv1["id"])
    assert row["totals"]["net_receivable"] == p.inv1["totals"]["net_receivable"]
    assert set(row) == {
        "id", "version", "doc_type", "status", "doc_number", "doc_date", "due_date",
        "valid_until", "project_id", "project_name", "is_gst_document", "is_ra_bill",
        "ra_sequence", "totals", "issued_at",
    }  # fmt: skip


def test_document_detail_with_lines_but_no_internal_references(p: Portal) -> None:
    r = p.portal(f"documents/{p.inv1['id']}")
    assert r.status_code == 200, r.content
    assert r.headers["ETag"] == f'"v{p.inv1["version"]}"'
    line = r.json()["lines"][0]
    assert line["description"] == p.inv1["lines"][0]["description"]
    assert "catalog_item_id" not in line
    assert "notes" not in r.json()
    for hidden in (p.draft["id"], p.others_bill["id"], str(uuid.uuid4())):
        assert p.portal(f"documents/{hidden}").status_code == 404
        assert p.portal(f"documents/{hidden}/pdf").status_code == 404


def test_pdf_is_made_on_request_when_missing(p: Portal) -> None:
    r = p.portal(f"documents/{p.inv1['id']}/pdf", query={"as": "link"})
    assert r.status_code in (200, 202), r.content


def test_accept_and_decline_quotations(p: Portal) -> None:
    no_if_match = APIClient().post(
        f"/api/v1/portal/documents/{p.quote['id']}/accept", {}, format="json", **p.h(p.me)
    )
    assert no_if_match.status_code == 428
    stale = p.answer(p.quote, "accept", version=p.quote["version"] + 5)
    assert stale.status_code == 412

    r = p.answer(p.quote, "accept")
    assert r.status_code == 200, r.content
    assert r.json()["status"] == "ACCEPTED"
    again = p.answer(r.json(), "decline")
    assert (again.status_code, code(again)) == (409, "not_issued")

    expired = p.answer(p.old_quote, "accept")
    assert (expired.status_code, code(expired)) == (409, "quotation_expired")
    not_a_quote = p.answer(p.inv1, "accept")
    assert (not_a_quote.status_code, code(not_a_quote)) == (409, "not_a_quotation")

    # the business sees the answer, and who gave it, in the audit log
    staff = APIClient().get(f"/api/v1/documents/{p.quote['id']}", **p.h())
    assert staff.json()["status"] == "ACCEPTED"


def test_decline(p: Portal) -> None:
    r = p.answer(p.quote, "decline")
    assert r.status_code == 200, r.content
    assert r.json()["status"] == "DECLINED"


def test_payments_received_without_voided_ones(p: Portal) -> None:
    r = p.portal("payments")
    assert r.status_code == 200, r.content
    rows = r.json()["results"]
    assert sorted(row["amount"] for row in rows) == ["100000.00", "300000.00"]
    paid = next(row for row in rows if row["amount"] == "300000.00")
    assert paid["allocations"] == [
        {
            "document_id": p.inv1["id"],
            "doc_number": p.inv1["doc_number"],
            "retention_release_id": None,
            "amount": "300000.00",
        }
    ]
    assert "notes" not in paid


def test_statement_matches_the_one_the_business_sees(p: Portal) -> None:
    period = {"from": "2026-10-01", "to": "2026-11-30"}
    mine = p.portal("statement", query=period)
    assert mine.status_code == 200, mine.content
    theirs = p.statement(**period).json()
    assert mine.json() == theirs
    assert mine.json()["closing_balance"] == "583016.00"


def test_projects_and_boq_progress(p: Portal) -> None:
    r = p.portal("projects")
    assert r.status_code == 200, r.content
    assert [row["code"] for row in r.json()["results"]] == ["TOWER", "VILLA-1"]
    progress = p.portal(f"projects/{p.project.pk}/boq-progress")
    assert progress.status_code == 200, progress.content
    assert "totals" in progress.json()
    assert p.portal(f"projects/{p.other_project.pk}/boq-progress").status_code == 404


def test_staff_cannot_use_the_portal(p: Portal) -> None:
    accountant = add_member(p.t, "ACCOUNTANT")
    for member in (p.owner, accountant):
        assert p.portal("me", member).status_code == 403
        assert p.portal("documents", member).status_code == 403


def test_a_client_session_without_the_emailed_code_cannot_use_the_portal(p: Portal) -> None:
    from apps.accounts.services import ClientInfo, _start_session

    tokens = _start_session(
        user_id=p.me.user_id,
        tenant_id=p.t.tenant_id,
        role="CLIENT",
        amr=frozenset({"pwd"}),
        client=ClientInfo(),
        party_id=p.client.pk,
    )
    r = APIClient().get("/api/v1/portal/me", HTTP_AUTHORIZATION=f"Bearer {tokens.access_token}")
    assert r.status_code == 403


def test_another_tenants_client_sees_none_of_it(p: Portal) -> None:
    from tests.factories import make_party

    elsewhere = make_tenant("Other Builder")
    stranger = add_client(elsewhere, make_party(elsewhere, "Their Client"))
    assert p.portal("documents", stranger).json()["results"] == []
    assert p.portal("payments", stranger).json()["results"] == []
    assert p.portal("projects", stranger).json()["results"] == []
    assert p.portal(f"documents/{p.inv1['id']}", stranger).status_code == 404
    assert p.portal(f"documents/{p.inv1['id']}/pdf", stranger).status_code == 404
    assert p.answer({**p.quote}, "accept").status_code == 200  # ours still works
    r = APIClient().post(
        f"/api/v1/portal/documents/{p.old_quote['id']}/decline",
        {},
        format="json",
        **p.h(stranger, IF_MATCH=f'"v{p.old_quote["version"]}"'),
    )
    assert r.status_code == 404
    assert p.portal(f"projects/{p.project.pk}/boq-progress", stranger).status_code == 404
    assert p.portal("statement", stranger).json()["entries"] == []
