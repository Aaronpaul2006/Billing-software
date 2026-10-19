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
    "auth-switch-tenant": "membership-checked (tests/accounts/test_auth.py)",
    "auth-mfa-setup": "caller's own account",
    "auth-mfa-enable": "caller's own account",
    "auth-mfa-disable": "caller's own account",
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
