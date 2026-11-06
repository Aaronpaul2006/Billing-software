"""Cross-tenant attacks against every endpoint (docs/01-architecture.md §8).

The route list is read from the URL conf, so a new endpoint cannot skip this:
every /api/v1 route must be registered below, either with an attack check
(tenant B against tenant A's data must get 404 and change nothing) or in
NOT_TENANT_DATA with a reason.
"""

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.test import APIClient

from apps.accounts.models import Membership
from apps.core.tenancy import tenant_context
from apps.tenants.models import DocumentSeries, GstRegistration
from tests.factories import Member, TenantFixture, add_member, make_tenant, make_user, owner_member

pytestmark = pytest.mark.django_db


def api_routes() -> Iterator[tuple[str, str | None]]:
    def walk(patterns: list[Any], prefix: str) -> Iterator[tuple[str, str | None]]:
        for p in patterns:
            if isinstance(p, URLResolver):
                yield from walk(p.url_patterns, prefix + str(p.pattern))
            elif isinstance(p, URLPattern):
                yield prefix + str(p.pattern), p.name

    for route, name in walk(get_resolver().url_patterns, ""):
        if route.startswith("api/v1/"):
            yield route, name


@dataclass
class World:
    """Tenant A (the victim) and tenant B (the attacker, OWNER with MFA)."""

    api: APIClient
    a: TenantFixture
    a_owner: Member
    a_member: Member
    a_invitation: uuid.UUID
    a_series: uuid.UUID
    b: TenantFixture
    b_owner: Member

    def as_b(self) -> dict[str, Any]:
        return {"HTTP_AUTHORIZATION": f"Bearer {self.b_owner.access_token}"}

    def a_owner_session_id(self) -> str:
        rows = self.api.get(
            "/api/v1/auth/sessions", HTTP_AUTHORIZATION=f"Bearer {self.a_owner.access_token}"
        ).json()["results"]
        return str(next(r["id"] for r in rows if r["current"]))


@pytest.fixture
def world() -> World:
    a, b = make_tenant("Victim Co"), make_tenant("Attacker Co")
    invitee = make_user("Invitee")
    with tenant_context(a.tenant_id, a.user_id):
        invitation = Membership.objects.create(
            tenant_id=a.tenant_id, user=invitee, role="VIEWER", status="INVITED"
        )
        series = DocumentSeries.objects.create(
            gst_registration_id=a.registration_id,
            doc_type="TAX_INVOICE",
            fy_start_year=2026,
            prefix="A/",
        )
    return World(
        api=APIClient(),
        a=a,
        a_owner=owner_member(a),
        a_member=add_member(a, "ACCOUNTANT"),
        a_invitation=invitation.pk,
        a_series=series.pk,
        b=b,
        b_owner=owner_member(b),
    )


def _membership(w: World, pk: uuid.UUID) -> tuple[str, str]:
    with tenant_context(w.a.tenant_id, w.a.user_id):
        m = Membership.objects.get(pk=pk)
    return m.role, m.status


# --- attacks on object routes (the URL contains an id) -----------------------------------


def attack_session_detail(w: World) -> None:
    session = w.a_owner_session_id()
    response = w.api.delete(f"/api/v1/auth/sessions/{session}", **w.as_b())
    assert response.status_code == 404
    me = w.api.get("/api/v1/me", HTTP_AUTHORIZATION=f"Bearer {w.a_owner.access_token}")
    assert me.status_code == 200


def attack_member_detail(w: World) -> None:
    url = f"/api/v1/members/{w.a_member.membership_id}"
    assert w.api.get(url, **w.as_b()).status_code in (404, 405)
    assert w.api.patch(url, {"role": "VIEWER"}, format="json", **w.as_b()).status_code == 404
    assert w.api.delete(url, **w.as_b()).status_code == 404
    assert _membership(w, w.a_member.membership_id) == ("ACCOUNTANT", "ACTIVE")


def attack_invitation(action: str) -> Callable[[World], None]:
    def attack(w: World) -> None:
        response = w.api.post(f"/api/v1/invitations/{w.a_invitation}/{action}", **w.as_b())
        assert response.status_code == 404
        assert _membership(w, w.a_invitation) == ("VIEWER", "INVITED")

    return attack


def _registration_name(w: World) -> str:
    with tenant_context(w.a.tenant_id, w.a.user_id):
        return str(GstRegistration.objects.get(pk=w.a.registration_id).legal_name)


def attack_gst_registration_detail(w: World) -> None:
    url = f"/api/v1/gst-registrations/{w.a.registration_id}"
    before = _registration_name(w)
    assert w.api.get(url, **w.as_b()).status_code == 404
    patched = w.api.patch(
        url, {"legal_name": "hijacked"}, format="json", HTTP_IF_MATCH='"v1"', **w.as_b()
    )
    assert patched.status_code == 404
    assert _registration_name(w) == before


def attack_document_series_detail(w: World) -> None:
    url = f"/api/v1/document-series/{w.a_series}"
    assert w.api.get(url, **w.as_b()).status_code == 404
    patched = w.api.patch(url, {"next_number": 99}, format="json", HTTP_IF_MATCH='"v1"', **w.as_b())
    assert patched.status_code == 404
    with tenant_context(w.a.tenant_id, w.a.user_id):
        assert DocumentSeries.objects.get(pk=w.a_series).next_number == 1


OBJECT_ROUTES: dict[str, Callable[[World], None]] = {
    "gst-registration-detail": attack_gst_registration_detail,
    "document-series-detail": attack_document_series_detail,
    "auth-session-detail": attack_session_detail,
    "member-detail": attack_member_detail,
    "invitation-accept": attack_invitation("accept"),
    "invitation-decline": attack_invitation("decline"),
}


# --- collection routes: tenant B's list never contains tenant A's rows ------------------


def list_members(w: World) -> None:
    ids = {m["id"] for m in w.api.get("/api/v1/members", **w.as_b()).json()["results"]}
    assert str(w.a_member.membership_id) not in ids
    assert str(w.a_owner.membership_id) not in ids


def list_sessions(w: World) -> None:
    rows = w.api.get("/api/v1/auth/sessions", **w.as_b()).json()["results"]
    assert {r["tenant_id"] for r in rows} == {str(w.b.tenant_id)}


def list_invitations(w: World) -> None:
    assert w.api.get("/api/v1/invitations", **w.as_b()).json()["results"] == []


def read_tenant(w: World) -> None:
    assert w.api.get("/api/v1/tenant", **w.as_b()).json()["id"] == str(w.b.tenant_id)


def list_gst_registrations(w: World) -> None:
    rows = w.api.get("/api/v1/gst-registrations", **w.as_b()).json()["results"]
    assert {r["id"] for r in rows} == {str(w.b.registration_id)}


def list_and_create_document_series(w: World) -> None:
    rows = w.api.get("/api/v1/document-series", **w.as_b()).json()["results"]
    assert str(w.a_series) not in {r["id"] for r in rows}
    # a series on tenant A's registration: refused as if it did not exist
    smuggled = w.api.post(
        "/api/v1/document-series",
        {
            "gst_registration_id": str(w.a.registration_id),
            "doc_type": "QUOTATION",
            "fy_start_year": 2026,
            "prefix": "X/",
        },
        format="json",
        **w.as_b(),
    )
    assert smuggled.status_code == 422
    assert smuggled.json()["errors"][0]["code"] == "not_found"


COLLECTION_ROUTES: dict[str, Callable[[World], None]] = {
    "tenant": read_tenant,
    "gst-registrations": list_gst_registrations,
    "document-series": list_and_create_document_series,
    "members": list_members,
    "auth-sessions": list_sessions,
    "invitations": list_invitations,
}

# Routes that hold no tenant data, or act only on the caller's own account.
NOT_TENANT_DATA = {
    "schema": "OpenAPI document",
    "auth-signup": "creates a new tenant",
    "auth-login": "credentials, no tenant data",
    "auth-mfa-verify": "credentials, no tenant data",
    "auth-refresh": "token rotation; tenant re-checked from the session",
    "auth-logout": "ends the caller's own session",
    "auth-verify-email": "signed link for one user's own address",
    "auth-verify-email-resend": "caller's own account",
    "auth-password-forgot": "public; same reply for every email",
    "auth-password-reset": "signed link for one user's own password",
    "auth-password-change": "caller's own account",
    "auth-email-confirm": "signed link for one user's own address",
    "auth-join": "signed invitation link; the tenant comes from our signature",
    "me-email": "caller's own account",
    "auth-switch-tenant": "membership-checked (tests/accounts/test_auth.py)",
    "auth-mfa-setup": "caller's own account",
    "auth-mfa-enable": "caller's own account",
    "auth-mfa-disable": "caller's own account",
    "auth-mfa-recovery-codes": "caller's own account",
    "me": "caller's own account",
}


def test_every_api_route_is_covered() -> None:
    all_names = [name for _, name in api_routes()]
    assert None not in all_names, "every API route needs a name"
    names = [n for n in all_names if n is not None]
    registered = set(OBJECT_ROUTES) | set(COLLECTION_ROUTES) | set(NOT_TENANT_DATA)
    missing = sorted(set(names) - registered)
    assert not missing, f"add these routes to the cross-tenant registry: {missing}"
    stale = sorted(registered - set(names))
    assert not stale, f"registered routes that no longer exist: {stale}"


def test_object_routes_are_exactly_those_with_ids() -> None:
    with_ids = {name for route, name in api_routes() if "<uuid:" in route}
    assert with_ids == set(OBJECT_ROUTES)


@pytest.mark.parametrize("name", sorted(OBJECT_ROUTES))
def test_object_route_rejects_other_tenant(world: World, name: str) -> None:
    OBJECT_ROUTES[name](world)


@pytest.mark.parametrize("name", sorted(COLLECTION_ROUTES))
def test_collection_route_hides_other_tenant(world: World, name: str) -> None:
    COLLECTION_ROUTES[name](world)


# --- Phase 1.3 master data -------------------------------------------------------------


@pytest.fixture
def masters(world: World) -> dict[str, str]:
    """One party, project, BOQ item and catalog item in tenant A."""
    from apps.catalog.models import CatalogItem
    from apps.parties.models import Party
    from apps.projects.models import BoqItem, Project

    a = world.a
    with tenant_context(a.tenant_id, a.user_id):
        party = Party.objects.create(
            display_name="A client", gst_treatment="UNREGISTERED", created_by_id=a.user_id
        )
        project = Project.objects.create(
            code="A1",
            name="A site",
            client_party=party,
            gst_registration_id=a.registration_id,
            site_state_code="32",
            created_by_id=a.user_id,
        )
        boq = BoqItem.objects.create(
            project=project, item_code="1", description="x", unit="nos", contract_qty=1, rate=1
        )
        item = CatalogItem.objects.create(name="A item")
    return {
        "party": str(party.pk),
        "project": str(project.pk),
        "boq": str(boq.pk),
        "catalog": str(item.pk),
    }


MASTER_OBJECT_URLS = {
    "party-detail": ("/api/v1/parties/{party}", {"display_name": "hijacked"}),
    "project-detail": ("/api/v1/projects/{project}", {"name": "hijacked"}),
    "boq-item-detail": ("/api/v1/boq-items/{boq}", {"description": "hijacked"}),
    "catalog-item-detail": ("/api/v1/catalog-items/{catalog}", {"name": "hijacked"}),
}


@pytest.mark.parametrize("name", sorted(MASTER_OBJECT_URLS))
def test_master_object_routes_reject_other_tenant(
    world: World, masters: dict[str, str], name: str
) -> None:
    template, change = MASTER_OBJECT_URLS[name]
    url = template.format(**masters)
    api = world.api
    assert api.get(url, **world.as_b()).status_code == 404
    assert (
        api.patch(url, change, format="json", HTTP_IF_MATCH='"v1"', **world.as_b()).status_code
        == 404
    )
    if name in ("boq-item-detail", "catalog-item-detail"):
        assert api.delete(url, **world.as_b()).status_code == 404
    as_a: dict[str, Any] = {"HTTP_AUTHORIZATION": f"Bearer {world.a_owner.access_token}"}
    assert api.get(url, **as_a).json()["version"] == 1  # untouched


def test_project_boq_items_route_rejects_other_tenant(
    world: World, masters: dict[str, str]
) -> None:
    url = f"/api/v1/projects/{masters['project']}/boq-items"
    assert world.api.get(url, **world.as_b()).status_code == 404
    body = {"item_code": "X", "description": "x", "unit": "nos", "contract_qty": "1", "rate": "1"}
    assert world.api.post(url, body, format="json", **world.as_b()).status_code == 404


def test_master_lists_and_references_hide_other_tenant(
    world: World, masters: dict[str, str]
) -> None:
    api = world.api
    for url, key in (
        ("/api/v1/parties", "party"),
        ("/api/v1/projects", "project"),
        ("/api/v1/catalog-items", "catalog"),
    ):
        ids = {r["id"] for r in api.get(url, **world.as_b()).json()["results"]}
        assert masters[key] not in ids
    smuggled = api.post(
        "/api/v1/projects",
        {
            "code": "B1",
            "name": "x",
            "client_party_id": masters["party"],
            "gst_registration_id": str(world.b.registration_id),
            "site_state_code": "32",
        },
        format="json",
        **world.as_b(),
    )
    assert smuggled.status_code == 422
    assert smuggled.json()["errors"][0]["code"] == "not_found"


for _name in MASTER_OBJECT_URLS:
    OBJECT_ROUTES[_name] = lambda w: (
        None
    )  # covered by test_master_object_routes_reject_other_tenant
OBJECT_ROUTES["project-boq-items"] = lambda w: None  # covered by the test above
for _name in ("parties", "projects", "catalog-items"):
    COLLECTION_ROUTES[_name] = lambda w: None  # covered by test_master_lists_and_references...


# --- Phase 1.5 documents -----------------------------------------------------------------


@pytest.fixture
def a_document(world: World, masters: dict[str, str]) -> str:
    from apps.documents.models import Document

    a = world.a
    with tenant_context(a.tenant_id, a.user_id):
        doc = Document.objects.create(
            doc_type="QUOTATION",
            gst_registration_id=a.registration_id,
            doc_date="2026-10-19",
            party_id=masters["party"],
            place_of_supply="32",
            supply_type="INTRA_STATE",
            notes="A's secret",
            created_by_id=a.user_id,
        )
    return str(doc.pk)


def test_document_detail_rejects_other_tenant(world: World, a_document: str) -> None:
    url, api = f"/api/v1/documents/{a_document}", world.api
    assert api.get(url, **world.as_b()).status_code == 404
    assert (
        api.patch(
            url, {"notes": "hijacked"}, format="json", HTTP_IF_MATCH='"v1"', **world.as_b()
        ).status_code
        == 404
    )
    assert api.delete(url, **world.as_b()).status_code == 404
    as_a: dict[str, Any] = {"HTTP_AUTHORIZATION": f"Bearer {world.a_owner.access_token}"}
    body = api.get(url, **as_a).json()
    assert (body["notes"], body["version"]) == ("A's secret", 1)


def test_documents_list_create_and_preview_hide_other_tenant(
    world: World, masters: dict[str, str], a_document: str
) -> None:
    api = world.api
    ids = {d["id"] for d in api.get("/api/v1/documents", **world.as_b()).json()["results"]}
    assert a_document not in ids
    payload = {
        "doc_type": "QUOTATION",
        "party_id": masters["party"],
        "doc_date": "2026-10-19",
        "lines": [{"description": "x", "quantity": "1", "rate": "1"}],
    }
    created = api.post(
        "/api/v1/documents",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        **world.as_b(),
    )
    assert created.status_code == 422
    assert created.json()["errors"][0]["code"] == "not_found"
    preview = api.post("/api/v1/documents:preview-totals", payload, format="json", **world.as_b())
    assert preview.status_code == 422


OBJECT_ROUTES["document-detail"] = lambda w: None  # test_document_detail_rejects_other_tenant
COLLECTION_ROUTES["documents"] = lambda w: None  # test_documents_list_create_and_preview...
COLLECTION_ROUTES["document-preview-totals"] = lambda w: None  # same test


# --- Phase 1.6 document lifecycle --------------------------------------------------------

LIFECYCLE_ACTIONS = {
    "document-issue": ("issue", {}),
    "document-cancel": ("cancel", {"reason": "hijack"}),
    "document-accept": ("accept", {}),
    "document-decline": ("decline", {}),
    "document-convert": ("convert", {"to": "TAX_INVOICE", "doc_date": "2026-10-20"}),
    "document-credit-notes": ("credit-notes", {"doc_date": "2026-10-20"}),
    "document-debit-notes": ("debit-notes", {"doc_date": "2026-10-20"}),
}


@pytest.mark.parametrize("name", sorted(LIFECYCLE_ACTIONS))
def test_lifecycle_actions_reject_other_tenant(world: World, a_document: str, name: str) -> None:
    action, body = LIFECYCLE_ACTIONS[name]
    response = world.api.post(
        f"/api/v1/documents/{a_document}/{action}",
        body,
        format="json",
        HTTP_IF_MATCH='"v1"',
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        **world.as_b(),
    )
    assert response.status_code == 404
    from apps.documents.models import Document

    with tenant_context(world.a.tenant_id, world.a.user_id):
        doc = Document.objects.get(pk=a_document)
        assert (doc.status, doc.version) == ("DRAFT", 1)
        assert Document.objects.count() == 1  # nothing converted or noted


for _name in LIFECYCLE_ACTIONS:
    OBJECT_ROUTES[_name] = lambda w: None  # test_lifecycle_actions_reject_other_tenant


def test_document_pdf_rejects_other_tenant(world: World, a_document: str) -> None:
    response = world.api.get(f"/api/v1/documents/{a_document}/pdf", **world.as_b())
    assert response.status_code == 404


OBJECT_ROUTES["document-pdf"] = lambda w: None  # test_document_pdf_rejects_other_tenant


# --- Phase 2.1 payments ------------------------------------------------------------------


@pytest.fixture
def a_payment(world: World, masters: dict[str, str]) -> dict[str, str]:
    """Tenant A: an issued invoice, a payment allocated 1.00 to it."""
    from django.db import connection
    from django.utils import timezone

    from apps.documents.models import Document, DocumentLine
    from apps.payments.models import Allocation, Payment

    a = world.a
    with tenant_context(a.tenant_id, a.user_id):
        series = (
            DocumentSeries.objects.create(
                gst_registration_id=a.registration_id,
                doc_type="TAX_INVOICE",
                fy_start_year=2026,
                prefix="A/",
            )
            if not DocumentSeries.objects.filter(doc_type="TAX_INVOICE").exists()
            else DocumentSeries.objects.get(doc_type="TAX_INVOICE")
        )
        doc = Document.objects.create(
            doc_type="TAX_INVOICE",
            gst_registration_id=a.registration_id,
            doc_date="2026-10-19",
            party_id=masters["party"],
            place_of_supply="32",
            supply_type="INTRA_STATE",
            subtotal=100,
            grand_total=100,
            net_receivable=100,
            created_by_id=a.user_id,
        )
        DocumentLine.objects.create(
            document=doc,
            line_no=1,
            description="x",
            quantity=1,
            rate=100,
            taxable_value=100,
            line_total=100,
        )
        with connection.cursor() as c:
            c.execute(
                "UPDATE documents SET status = 'ISSUED', series_id = %s, doc_number = 'A/9',"
                " issued_at = %s, issued_by = %s, supplier_snapshot = '{}', party_snapshot = '{}'"
                " WHERE id = %s",
                [series.pk, timezone.now(), a.user_id, doc.pk],
            )
        payment = Payment.objects.create(
            party_id=masters["party"],
            payment_date="2026-10-20",
            amount=50,
            mode="UPI",
            created_by_id=a.user_id,
        )
        allocation = Allocation.objects.create(
            document=doc, payment=payment, amount=1, created_by_id=a.user_id
        )
    return {"invoice": str(doc.pk), "payment": str(payment.pk), "allocation": str(allocation.pk)}


def _a_state(world: World, ids: dict[str, str]) -> tuple[object, ...]:
    from apps.documents.models import Document
    from apps.payments.models import Allocation, Payment

    with tenant_context(world.a.tenant_id, world.a.user_id):
        p = Payment.objects.get(pk=ids["payment"])
        return (
            p.status,
            p.version,
            Allocation.objects.count(),
            Document.objects.get(pk=ids["invoice"]).amount_settled,
        )


def test_payment_routes_reject_other_tenant(world: World, a_payment: dict[str, str]) -> None:
    api, b = world.api, world.as_b()
    before = _a_state(world, a_payment)
    pay = a_payment["payment"]
    assert api.get(f"/api/v1/payments/{pay}", **b).status_code == 404
    assert (
        api.post(
            f"/api/v1/payments/{pay}/allocations",
            {"allocations": [{"document_id": a_payment["invoice"], "amount": "1.00"}]},
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
            **b,
        ).status_code
        == 404
    )
    assert (
        api.post(
            f"/api/v1/payments/{pay}/void",
            {"reason": "hijack"},
            format="json",
            HTTP_IF_MATCH='"v1"',
            **b,
        ).status_code
        == 404
    )
    assert api.delete(f"/api/v1/allocations/{a_payment['allocation']}", **b).status_code == 404
    assert _a_state(world, a_payment) == before


def test_payments_list_and_create_hide_other_tenant(
    world: World, masters: dict[str, str], a_payment: dict[str, str]
) -> None:
    api, b = world.api, world.as_b()
    ids = {p["id"] for p in api.get("/api/v1/payments", **b).json()["results"]}
    assert a_payment["payment"] not in ids
    smuggled = api.post(
        "/api/v1/payments",
        {
            "party_id": masters["party"],
            "payment_date": "2026-10-20",
            "amount": "1.00",
            "mode": "UPI",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        **b,
    )
    assert smuggled.status_code == 422
    assert smuggled.json()["errors"][0]["code"] == "not_found"


for _name in ("payment-detail", "payment-allocations", "payment-void", "allocation-detail"):
    OBJECT_ROUTES[_name] = lambda w: None  # test_payment_routes_reject_other_tenant
COLLECTION_ROUTES["payments"] = lambda w: None  # test_payments_list_and_create_hide_other_tenant


def test_document_allocations_reject_other_tenant(world: World, a_payment: dict[str, str]) -> None:
    url = f"/api/v1/documents/{a_payment['invoice']}/allocations"
    before = _a_state(world, a_payment)
    assert world.api.get(url, **world.as_b()).status_code == 404
    applied = world.api.post(
        url,
        {"allocations": [{"document_id": a_payment["invoice"], "amount": "1.00"}]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        **world.as_b(),
    )
    assert applied.status_code == 404
    assert _a_state(world, a_payment) == before


OBJECT_ROUTES["document-allocations"] = lambda w: (
    None
)  # test_document_allocations_reject_other_tenant


# --- Phase 2.3 expenses --------------------------------------------------------------


def test_expense_routes_reject_other_tenant(world: World, masters: dict[str, str]) -> None:
    from apps.expenses.models import Expense

    a = world.a
    with tenant_context(a.tenant_id, a.user_id):
        expense = Expense.objects.create(
            category="MATERIAL",
            expense_date="2026-10-20",
            description="A's cement",
            taxable_value=100,
            total_amount=100,
            created_by_id=a.user_id,
        )
    api, b = world.api, world.as_b()
    url = f"/api/v1/expenses/{expense.pk}"
    assert api.get(url, **b).status_code == 404
    assert (
        api.patch(
            url, {"description": "hijacked"}, format="json", HTTP_IF_MATCH='"v1"', **b
        ).status_code
        == 404
    )
    assert api.post(f"{url}/void", {}, format="json", HTTP_IF_MATCH='"v1"', **b).status_code == 404
    assert str(expense.pk) not in {
        e["id"] for e in api.get("/api/v1/expenses", **b).json()["results"]
    }
    smuggled = api.post(
        "/api/v1/expenses",
        {
            "project_id": masters["project"],
            "category": "MATERIAL",
            "expense_date": "2026-10-20",
            "description": "x",
            "taxable_value": "1.00",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        **b,
    )
    assert smuggled.status_code == 422
    with tenant_context(a.tenant_id, a.user_id):
        e = Expense.objects.get(pk=expense.pk)
        assert (e.description, e.status, e.version) == ("A's cement", "RECORDED", 1)


for _name in ("expense-detail", "expense-void"):
    OBJECT_ROUTES[_name] = lambda w: None  # test_expense_routes_reject_other_tenant
COLLECTION_ROUTES["expenses"] = lambda w: None  # same test


# --- Phase 2.4 reports ---------------------------------------------------------------

REPORT_LISTS = {
    "report-billing-by-month": "/api/v1/reports/billing-by-month",
    "report-receivables": "/api/v1/reports/receivables",
    "report-projects": "/api/v1/reports/projects",
    "report-gst-summary": "/api/v1/reports/gst-summary?period=2026-10",
}
PERIOD = "from=2026-10-01&to=2026-10-31"


def test_reports_hide_other_tenant(
    world: World, masters: dict[str, str], a_payment: dict[str, str]
) -> None:
    from apps.expenses.models import Expense

    a = world.a
    with tenant_context(a.tenant_id, a.user_id):
        Expense.objects.create(
            category="MATERIAL",
            expense_date="2026-10-20",
            description="A's cement",
            taxable_value=100,
            total_amount=100,
            created_by_id=a.user_id,
        )
    api, b = world.api, world.as_b()
    as_a: dict[str, Any] = {"HTTP_AUTHORIZATION": f"Bearer {world.a_owner.access_token}"}

    def get(url: str, headers: dict[str, Any]) -> Any:
        sep = "&" if "?" in url else "?"
        r = api.get(f"{url}{sep}{PERIOD}" if "gst" not in url else url, **headers)
        assert r.status_code == 200, r.content
        return r.json()

    seen_by_a = get("/api/v1/reports/summary", as_a)["current"]
    assert (seen_by_a["billed"], seen_by_a["collected"], seen_by_a["expenses"]) == (
        "100.00",
        "50.00",
        "100.00",
    )
    assert set(get("/api/v1/reports/summary", b)["current"].values()) == {"0.00"}
    for name, url in REPORT_LISTS.items():
        assert get(url, as_a)["results"], name  # A's data is there...
        assert get(url, b)["results"] == [], name  # ...and B sees none of it
    assert api.get(f"/api/v1/reports/projects/{masters['project']}", **as_a).status_code == 200
    assert api.get(f"/api/v1/reports/projects/{masters['project']}", **b).status_code == 404


for _name in ("report-summary", *REPORT_LISTS):
    COLLECTION_ROUTES[_name] = lambda w: None  # test_reports_hide_other_tenant
OBJECT_ROUTES["report-project"] = lambda w: None  # same test


# --- W.1 statement of account -----------------------------------------------------------


def test_statement_rejects_other_tenant_party(world: World, masters: dict[str, str]) -> None:
    api, b = world.api, world.as_b()
    url = f"/api/v1/parties/{masters['party']}/statement"
    as_a: dict[str, Any] = {"HTTP_AUTHORIZATION": f"Bearer {world.a_owner.access_token}"}
    assert api.get(url, **as_a).status_code == 200
    assert api.get(url, **b).status_code == 404


OBJECT_ROUTES["party-statement"] = lambda w: None  # test_statement_rejects_other_tenant_party


# --- W.2 payment reminders --------------------------------------------------------------


def test_reminders_reject_other_tenant_document(world: World, a_document: str) -> None:
    api, b = world.api, world.as_b()
    url = f"/api/v1/documents/{a_document}/reminders"
    assert api.get(url, **b).status_code == 404
    r = api.post(url, {}, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()), **b)
    assert r.status_code == 404


OBJECT_ROUTES["document-reminders"] = lambda w: None  # test_reminders_reject_other_tenant_document


# --- W.3 document templates -------------------------------------------------------------


def test_templates_reject_other_tenant(
    world: World, masters: dict[str, str], a_document: str
) -> None:
    from apps.doc_templates.models import DocumentTemplate

    a = world.a
    with tenant_context(a.tenant_id, a.user_id):
        template = DocumentTemplate.objects.create(
            name="A's secret package",
            doc_type="QUOTATION",
            lines=[
                {
                    "description": "x",
                    "quantity": "1",
                    "rate": "1.00",
                    "gst_rate": "18.00",
                    "discount_amount": "0.00",
                }
            ],
            created_by_id=a.user_id,
        )
    api, b = world.api, world.as_b()
    url = f"/api/v1/document-templates/{template.pk}"
    assert api.get(url, **b).status_code == 404
    assert (
        api.patch(url, {"name": "mine"}, format="json", HTTP_IF_MATCH='"v1"', **b).status_code
        == 404
    )
    assert api.delete(url, **b).status_code == 404
    r = api.post(
        f"{url}/use",
        {"party_id": masters["party"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        **b,
    )
    assert r.status_code == 404
    r = api.post(
        f"/api/v1/documents/{a_document}/save-as-template",
        {"name": "stolen"},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        **b,
    )
    assert r.status_code == 404
    assert api.get("/api/v1/document-templates", **b).json()["results"] == []


for _name in ("document-template-detail", "document-template-use", "document-save-as-template"):
    OBJECT_ROUTES[_name] = lambda w: None  # test_templates_reject_other_tenant
COLLECTION_ROUTES["document-templates"] = lambda w: None  # same test


# --- W.4 catalog variants ---------------------------------------------------------------


def test_catalog_variants_reject_other_tenant(world: World) -> None:
    from apps.catalog.models import CatalogItem, CatalogItemVariant

    a = world.a
    with tenant_context(a.tenant_id, a.user_id):
        item = CatalogItem.objects.create(name="A's cement")
        variant = CatalogItemVariant.objects.create(
            catalog_item=item, attribute="Brand", value="Secret"
        )
    api, b = world.api, world.as_b()
    assert api.get(f"/api/v1/catalog-items/{item.pk}/variants", **b).status_code == 404
    r = api.post(
        f"/api/v1/catalog-items/{item.pk}/variants",
        {"attribute": "Brand", "value": "Mine"},
        format="json",
        **b,
    )
    assert r.status_code == 404
    url = f"/api/v1/catalog-variants/{variant.pk}"
    assert api.get(url, **b).status_code == 404
    assert (
        api.patch(url, {"value": "x"}, format="json", HTTP_IF_MATCH='"v1"', **b).status_code == 404
    )
    assert api.delete(url, **b).status_code == 404


OBJECT_ROUTES["catalog-item-variants"] = lambda w: None  # test_catalog_variants_reject_other_tenant
OBJECT_ROUTES["catalog-variant-detail"] = lambda w: None  # same test


# --- Phase 3.1 BOQ import ------------------------------------------------------------


def test_boq_import_rejects_other_tenant(world: World, masters: dict[str, str]) -> None:
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.projects.models import BoqItem

    csv = b"item_code,description,unit,contract_qty,rate\n9,Smuggled,nos,1,1\n"
    for dry_run in ("true", "false"):
        r = world.api.post(
            f"/api/v1/projects/{masters['project']}/boq-items:import",
            {"file": SimpleUploadedFile("b.csv", csv), "dry_run": dry_run},
            format="multipart",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
            **world.as_b(),
        )
        assert r.status_code == 404, r.content
    with tenant_context(world.a.tenant_id, world.a.user_id):
        assert not BoqItem.objects.filter(item_code="9").exists()


OBJECT_ROUTES["project-boq-import"] = lambda w: None  # test_boq_import_rejects_other_tenant


# --- Phase 3.2 RA bills ----------------------------------------------------------------


def test_boq_progress_and_ra_bills_reject_other_tenant(
    world: World, masters: dict[str, str]
) -> None:
    api, b = world.api, world.as_b()
    url = f"/api/v1/projects/{masters['project']}/boq-progress"
    as_a: dict[str, Any] = {"HTTP_AUTHORIZATION": f"Bearer {world.a_owner.access_token}"}
    assert [r["item_code"] for r in api.get(url, **as_a).json()["results"]] == ["1"]
    assert api.get(url, **b).status_code == 404
    # B cannot bill A's BOQ item in an RA bill on A's project (both unknown to B)
    r = api.post(
        "/api/v1/documents",
        {
            "doc_type": "TAX_INVOICE",
            "party_id": masters["party"],
            "project_id": masters["project"],
            "doc_date": "2026-10-19",
            "is_ra_bill": True,
            "lines": [{"boq_item_id": masters["boq"], "quantity": "1"}],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        **b,
    )
    assert (r.status_code, r.json()["errors"][0]["code"]) == (422, "not_found")


OBJECT_ROUTES["project-boq-progress"] = lambda w: None  # same test


# --- Phase 3.3 retention releases ------------------------------------------------------


def test_retention_routes_reject_other_tenant(world: World, masters: dict[str, str]) -> None:
    from apps.payments.models import Payment, RetentionRelease

    a = world.a
    with tenant_context(a.tenant_id, a.user_id):
        release = RetentionRelease.objects.create(
            project_id=masters["project"],
            party_id=masters["party"],
            book="GST",
            release_date="2026-11-05",
            amount=1000,
            created_by_id=a.user_id,
        )
    api, b = world.api, world.as_b()
    url = f"/api/v1/retention-releases/{release.pk}"
    assert api.get(url, **b).status_code == 404
    cancel = api.post(
        f"{url}/cancel",
        {"reason": "hijack"},
        format="json",
        HTTP_IF_MATCH='"v1"',
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        **b,
    )
    assert cancel.status_code == 404
    assert api.get("/api/v1/retention-releases", **b).json()["results"] == []
    assert api.get(f"/api/v1/projects/{masters['project']}/retention", **b).status_code == 404
    smuggled = api.post(
        "/api/v1/retention-releases",
        {"project_id": masters["project"], "release_date": "2026-11-05", "amount": "1.00"},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        **b,
    )
    assert (smuggled.status_code, smuggled.json()["errors"][0]["code"]) == (422, "not_found")
    with tenant_context(world.b.tenant_id, world.b.user_id):
        from apps.parties.models import Party

        b_party = Party.objects.create(
            display_name="B client", gst_treatment="UNREGISTERED", created_by_id=world.b.user_id
        )
        b_payment = Payment.objects.create(
            party=b_party,
            payment_date="2026-11-06",
            amount=100,
            mode="UPI",
            created_by_id=world.b.user_id,
        )
    r = api.post(
        f"/api/v1/payments/{b_payment.pk}/allocations",
        {"allocations": [{"retention_release_id": str(release.pk), "amount": "1.00"}]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        **b,
    )
    assert (r.status_code, r.json()["errors"][0]["code"]) == (422, "not_found")
    with tenant_context(a.tenant_id, a.user_id):
        r_a = RetentionRelease.objects.get(pk=release.pk)
        assert (r_a.status, r_a.amount_settled, r_a.version) == ("RELEASED", 0, 1)


for _name in ("retention-release-detail", "retention-release-cancel", "project-retention"):
    OBJECT_ROUTES[_name] = lambda w: None  # test_retention_routes_reject_other_tenant
COLLECTION_ROUTES["retention-releases"] = lambda w: None  # same test


# --- Phase 3.4 TDS certificates --------------------------------------------------------


def test_tds_routes_reject_other_tenant(world: World, masters: dict[str, str]) -> None:
    from apps.tds.models import TdsCertificate

    a = world.a
    with tenant_context(a.tenant_id, a.user_id):
        cert = TdsCertificate.objects.create(
            party_id=masters["party"],
            deductor_tan="BLRS12345E",
            fy_start_year=2026,
            quarter=3,
            certificate_number="QWERTYU",
            tds_amount=100,
            created_by_id=a.user_id,
        )
    api, b = world.api, world.as_b()
    url = f"/api/v1/tds-certificates/{cert.pk}"
    assert api.get(url, **b).status_code == 404
    assert (
        api.patch(url, {"tds_amount": "1.00"}, format="json", HTTP_IF_MATCH='"v1"', **b).status_code
        == 404
    )
    assert api.delete(url, **b).status_code == 404
    assert api.get("/api/v1/tds-certificates", **b).json()["results"] == []
    report = "/api/v1/reports/tds-reconciliation?fy=2026"
    as_a: dict[str, Any] = {"HTTP_AUTHORIZATION": f"Bearer {world.a_owner.access_token}"}
    assert [r["certified"] for r in api.get(report, **as_a).json()["results"]] == ["100.00"]
    assert api.get(report, **b).json()["results"] == []
    smuggled = api.post(
        "/api/v1/tds-certificates",
        {
            "party_id": masters["party"],
            "deductor_tan": "BLRS12345E",
            "fy_start_year": 2026,
            "quarter": 3,
            "certificate_number": "OTHER01",
            "tds_amount": "1.00",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        **b,
    )
    assert (smuggled.status_code, smuggled.json()["errors"][0]["code"]) == (422, "not_found")
    with tenant_context(a.tenant_id, a.user_id):
        assert TdsCertificate.objects.get(pk=cert.pk).tds_amount == 100


OBJECT_ROUTES["tds-certificate-detail"] = lambda w: None  # test_tds_routes_reject_other_tenant
COLLECTION_ROUTES["tds-certificates"] = lambda w: None  # same test
COLLECTION_ROUTES["report-tds-reconciliation"] = lambda w: None  # same test


# --- L.3 uploads -------------------------------------------------------------------------


def test_attachment_routes_reject_other_tenant(world: World) -> None:
    from apps.files.models import Attachment

    a = world.a
    with tenant_context(a.tenant_id, a.user_id):
        attachment = Attachment.objects.create(
            storage_key=f"tenants/{a.tenant_id}/uploads/x.pdf",
            original_filename="a.pdf",
            content_type="application/pdf",
            size_bytes=10,
            uploaded_by_id=a.user_id,
        )
    api, b = world.api, world.as_b()
    assert api.get(f"/api/v1/attachments/{attachment.pk}", **b).status_code == 404
    assert api.post(f"/api/v1/attachments/{attachment.pk}/complete", **b).status_code == 404
    with tenant_context(a.tenant_id, a.user_id):
        assert Attachment.objects.get(pk=attachment.pk).status == "PENDING"


OBJECT_ROUTES["attachment-detail"] = lambda w: None  # test_attachment_routes_reject_other_tenant
OBJECT_ROUTES["attachment-complete"] = lambda w: None  # same test
NOT_TENANT_DATA["attachments"] = "creates an upload in the caller's own tenant"


# --- E.1 exports -------------------------------------------------------------------------


def test_export_routes_reject_other_tenant(world: World) -> None:
    from apps.exports.models import Export

    a = world.a
    with tenant_context(a.tenant_id, a.user_id):
        export = Export.objects.create(
            kind="PAYMENTS",
            format="CSV",
            params={"from": "2026-04-01", "to": "2026-10-21"},
            requested_by_id=world.a_owner.user_id,
        )
    api, b = world.api, world.as_b()
    assert api.get(f"/api/v1/exports/{export.pk}", **b).status_code == 404
    assert api.get("/api/v1/exports", **b).json()["results"] == []


def test_boq_export_rejects_other_tenant_project(world: World, masters: dict[str, str]) -> None:
    r = world.api.post(
        "/api/v1/exports",
        {"kind": "BOQ", "format": "CSV", "params": {"project_id": masters["project"]}},
        format="json",
        **world.as_b(),
    )
    assert r.status_code == 422, r.content  # A's project is unknown to B
    assert r.json()["errors"][0]["field"] == "params.project_id"


OBJECT_ROUTES["export-detail"] = lambda w: None  # test_export_routes_reject_other_tenant
COLLECTION_ROUTES["exports"] = lambda w: None  # same test


# --- K.2 invitations by email -------------------------------------------------------------


def test_email_invitation_routes_reject_other_tenant(world: World) -> None:
    from apps.accounts.models import EmailInvitation

    a = world.a
    with tenant_context(a.tenant_id, a.user_id):
        invitation = EmailInvitation.objects.create(
            email="newcomer@example.com", role="VIEWER", invited_by_id=a.user_id
        )
    api, b = world.api, world.as_b()
    url = f"/api/v1/email-invitations/{invitation.pk}"
    assert api.get("/api/v1/email-invitations", **b).json()["results"] == []
    assert api.delete(url, **b).status_code == 404
    assert api.post(f"{url}/resend", **b).status_code == 404
    with tenant_context(a.tenant_id, a.user_id):
        assert EmailInvitation.objects.get(pk=invitation.pk).status == "PENDING"


OBJECT_ROUTES["email-invitation-detail"] = lambda w: None  # test_email_invitation_routes_...
OBJECT_ROUTES["email-invitation-resend"] = lambda w: None  # same test
COLLECTION_ROUTES["email-invitations"] = lambda w: None  # same test


# --- W.5a client-portal users ----------------------------------------------------------

# tests/accounts/test_client_portal.py::test_portal_user_routes_reject_another_tenants_client
OBJECT_ROUTES["portal-users"] = lambda w: None
OBJECT_ROUTES["portal-user-detail"] = lambda w: None


# --- W.5b client portal: tests/portal/test_portal.py::test_another_tenants_client_sees_none_of_it

for _name in (
    "portal-document-detail",
    "portal-document-pdf",
    "portal-document-accept",
    "portal-document-decline",
    "portal-boq-progress",
):
    OBJECT_ROUTES[_name] = lambda w: None
for _name in ("portal-documents", "portal-payments", "portal-projects", "portal-statement"):
    COLLECTION_ROUTES[_name] = lambda w: None
NOT_TENANT_DATA["portal-me"] = "the caller's own client and business (tests/portal)"

# --- W.6 main dashboard: tests/reports/test_dashboard.py::test_another_tenant_sees_only_its_own
COLLECTION_ROUTES["report-dashboard"] = lambda w: None

# --- H.2 setup checklist: tests/tenants/test_setup.py::test_another_tenant_is_not_counted
COLLECTION_ROUTES["tenant-setup"] = lambda w: None

# --- B.2 catalog import: tests/catalog/test_import.py::test_imports_stay_in_the_tenant
COLLECTION_ROUTES["catalog-import"] = lambda w: None
NOT_TENANT_DATA["catalog-import-sample"] = "a fixed sample file"

# --- B.3 client import: tests/masters/test_party_import.py::test_imports_stay_in_the_tenant
COLLECTION_ROUTES["party-import"] = lambda w: None
NOT_TENANT_DATA["party-import-sample"] = "a fixed sample file"

# --- B.7 lines from a file or pasted cells: reads nothing stored
NOT_TENANT_DATA["document-parse-lines"] = "checks the cells sent; reads and saves nothing"
NOT_TENANT_DATA["document-lines-sample"] = "a fixed sample file"

# --- B.8 last rates: tests/documents/test_last_rates.py::test_another_tenants_client_is_not_found
OBJECT_ROUTES["party-last-rates"] = lambda w: None

# --- B.10 duplicate: tests/documents/test_duplicate.py::test_another_tenants_bill_is_not_found
OBJECT_ROUTES["document-duplicate"] = lambda w: None
# --- B.11 history: tests/documents/test_history.py::test_another_tenants_bill_is_not_found
OBJECT_ROUTES["document-history"] = lambda w: None

# --- B.12 print settings: tests/tenants/test_print_settings.py::test_another_business_sees_only_its_own
COLLECTION_ROUTES["tenant-print-settings"] = lambda w: None

# --- B.14 review: tests/documents/test_review.py::test_another_tenants_bill_is_not_found
OBJECT_ROUTES["document-review"] = lambda w: None

# --- B.15 email: tests/documents/test_sending.py::test_another_tenants_bill_is_not_found
OBJECT_ROUTES["document-email"] = lambda w: None

# --- B.16 Tally ledger names: tests/exports/test_tally.py::test_ledger_names_are_per_business
COLLECTION_ROUTES["tenant-tally-settings"] = lambda w: None

# --- D.6 command palette search: tests/search/test_search.py::test_another_business_sees_nothing
COLLECTION_ROUTES["search"] = lambda w: None

# --- Part B activity log: tests/audit/test_activity_log.py::test_another_business_sees_nothing_of_it
COLLECTION_ROUTES["audit-log"] = lambda w: None

# --- Payables part 1: tests/payables/test_api.py::test_another_business_reaches_none_of_it
for _name in (
    "vendor-bill-detail",
    "vendor-bill-void",
    "vendor-payment-detail",
    "vendor-payment-void",
):
    OBJECT_ROUTES[_name] = lambda w: None
for _name in ("vendor-bills", "vendor-bill-tds-suggestion", "vendor-payments", "report-payables"):
    COLLECTION_ROUTES[_name] = lambda w: None

# --- Bank statements: tests/banking/test_api.py::test_another_business_reaches_none_of_it
for _name in ("bank-line-match", "bank-line-record", "bank-line-ignore", "bank-line-reopen"):
    OBJECT_ROUTES[_name] = lambda w: None
for _name in ("bank-statement-preview", "bank-statement-import", "bank-lines", "bank-accounts"):
    COLLECTION_ROUTES[_name] = lambda w: None

# --- Cash-flow forecast: tests/reports/test_cashflow.py::test_another_business_sees_none_of_it
COLLECTION_ROUTES["report-cash-flow"] = lambda w: None

# --- Tally masters import: tests/parties/test_tally_import.py::test_another_business_is_not_affected
COLLECTION_ROUTES["tally-import"] = lambda w: None
