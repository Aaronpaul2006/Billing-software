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
    return World(
        api=APIClient(),
        a=a,
        a_owner=owner_member(a),
        a_member=add_member(a, "ACCOUNTANT"),
        a_invitation=invitation.pk,
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


OBJECT_ROUTES: dict[str, Callable[[World], None]] = {
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


COLLECTION_ROUTES: dict[str, Callable[[World], None]] = {
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
