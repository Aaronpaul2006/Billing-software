"""Client portal, security and sign-in (W.5a): portal users of a client,
sign-in with an emailed code, and staff endpoints refusing client sessions."""

import re
import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from django.contrib.auth.hashers import make_password
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import AuthSession, Membership, User
from apps.accounts.tokens import verify_access_token
from apps.core.tenancy import tenant_context
from apps.parties.models import Party
from tests.factories import (
    TenantFixture,
    add_client,
    add_member,
    make_party,
    make_tenant,
    make_user,
    owner_member,
)
from tests.tenancy.test_cross_tenant_endpoints import NOT_TENANT_DATA, api_routes

pytestmark = pytest.mark.django_db

PASSWORD = "a long enough passphrase"


@pytest.fixture
def api() -> APIClient:
    client = APIClient()
    client.default_format = "json"
    return client


@pytest.fixture
def company() -> TenantFixture:
    return make_tenant("Nair Constructions")


@pytest.fixture
def party(company: TenantFixture) -> Party:
    return make_party(company, "Kurian Homes")


def _as(token: str) -> dict[str, Any]:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def _code(response: Any) -> str:
    body = response.json()
    return str(body["errors"][0]["code"] if body["code"] == "validation_error" else body["code"])


def _portal_url(party: Party | uuid.UUID) -> str:
    pk = party.pk if isinstance(party, Party) else party
    return f"/api/v1/parties/{pk}/portal-users"


def _client_account(company: TenantFixture, party: Party, email: str) -> User:
    user = User.objects.create(
        email=email, password_hash=make_password(PASSWORD), full_name="Anna Kurian"
    )
    with tenant_context(company.tenant_id, company.user_id):
        Membership.objects.create(
            tenant_id=company.tenant_id, user=user, role="CLIENT", party=party
        )
    return user


def _emailed_code() -> str:
    match = re.search(r"Your sign-in code is (\d{6})\.", str(mail.outbox[-1].body))
    assert match, mail.outbox[-1].body
    return match.group(1)


# --- sign-in with an emailed code -----------------------------------------------------


def test_portal_user_signs_in_with_password_and_emailed_code(
    api: APIClient, company: TenantFixture, party: Party, django_capture_on_commit_callbacks: Any
) -> None:
    _client_account(company, party, "anna@example.com")
    with django_capture_on_commit_callbacks(execute=True):
        first = api.post("/api/v1/auth/login", {"email": "anna@example.com", "password": PASSWORD})
    assert first.status_code == 200, first.content
    assert first.json()["mfa_required"] is True
    assert first.json()["mfa_method"] == "email"
    assert "access_token" not in first.json()
    assert mail.outbox[-1].to == ["anna@example.com"]
    code = _emailed_code()

    done = api.post(
        "/api/v1/auth/mfa/verify", {"mfa_token": first.json()["mfa_token"], "code": code}
    )
    assert done.status_code == 200, done.content
    body = done.json()
    assert body["role"] == "CLIENT"
    principal = verify_access_token(body["access_token"])
    assert principal.amr == {"pwd", "email"}
    assert principal.party_id == party.pk

    # used up: the same code does not work twice
    again = api.post(
        "/api/v1/auth/mfa/verify", {"mfa_token": first.json()["mfa_token"], "code": code}
    )
    assert again.status_code == 401
    assert _code(again) == "invalid_mfa_code"


def test_refresh_keeps_the_emailed_code_sign_in(
    api: APIClient, company: TenantFixture, party: Party
) -> None:
    client = add_client(company, party)
    refreshed = api.post("/api/v1/auth/token/refresh", {"refresh_token": client.refresh_token})
    assert refreshed.status_code == 200, refreshed.content
    principal = verify_access_token(refreshed.json()["access_token"])
    assert principal.amr == {"pwd", "email"}
    assert principal.party_id == party.pk


def test_five_wrong_codes_end_the_attempt(
    api: APIClient, company: TenantFixture, party: Party, django_capture_on_commit_callbacks: Any
) -> None:
    user = _client_account(company, party, "anna@example.com")
    with django_capture_on_commit_callbacks(execute=True):
        first = api.post("/api/v1/auth/login", {"email": "anna@example.com", "password": PASSWORD})
    token, code = first.json()["mfa_token"], _emailed_code()
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        r = api.post("/api/v1/auth/mfa/verify", {"mfa_token": token, "code": wrong})
        assert r.status_code == 401
    User.objects.filter(pk=user.pk).update(failed_login_count=0, locked_until=None)
    late = api.post("/api/v1/auth/mfa/verify", {"mfa_token": token, "code": code})
    assert late.status_code == 401  # even the right code: sign in again for a new one


def test_an_expired_code_is_refused(
    api: APIClient, company: TenantFixture, party: Party, django_capture_on_commit_callbacks: Any
) -> None:
    user = _client_account(company, party, "anna@example.com")
    with django_capture_on_commit_callbacks(execute=True):
        first = api.post("/api/v1/auth/login", {"email": "anna@example.com", "password": PASSWORD})
    User.objects.filter(pk=user.pk).update(
        email_code_expires_at=timezone.now() - timedelta(seconds=1)
    )
    r = api.post(
        "/api/v1/auth/mfa/verify", {"mfa_token": first.json()["mfa_token"], "code": _emailed_code()}
    )
    assert r.status_code == 401


def test_staff_without_a_portal_membership_sign_in_as_before(
    api: APIClient, company: TenantFixture
) -> None:
    user = make_user("Staff Person")
    User.objects.filter(pk=user.pk).update(password_hash=make_password(PASSWORD))
    with tenant_context(company.tenant_id, company.user_id):
        Membership.objects.create(tenant_id=company.tenant_id, user=user, role="ACCOUNTANT")
    r = api.post("/api/v1/auth/login", {"email": user.email, "password": PASSWORD})
    assert r.status_code == 200
    assert "access_token" in r.json()
    assert mail.outbox == []


def test_a_client_session_without_the_second_step_is_refused(
    api: APIClient, company: TenantFixture, party: Party
) -> None:
    from apps.accounts.services import ClientInfo, _start_session

    client = add_client(company, party)
    tokens = _start_session(
        user_id=client.user_id,
        tenant_id=company.tenant_id,
        role="CLIENT",
        amr=frozenset({"pwd"}),
        client=ClientInfo(),
        party_id=party.pk,
    )
    r = api.get("/api/v1/invitations", **_as(tokens.access_token))
    assert r.status_code == 200  # own invitations: allowed for everyone
    r = api.get(f"/api/v1/parties/{party.pk}/statement", **_as(tokens.access_token))
    assert r.status_code == 403


# --- staff endpoints refuse client sessions -------------------------------------------

# Routes about the caller's own account, which a client may use too.
CLIENT_MAY_USE = set(NOT_TENANT_DATA) | {
    "auth-sessions",
    "auth-session-detail",
    "invitations",
    "invitation-accept",
    "invitation-decline",
}


def test_every_staff_route_refuses_a_client_session(
    api: APIClient, company: TenantFixture, party: Party
) -> None:
    client = add_client(company, party)
    headers = {
        **_as(client.access_token),
        "HTTP_IF_MATCH": '"v1"',
        "HTTP_IDEMPOTENCY_KEY": str(uuid.uuid4()),
    }
    leaks = []
    for route, name in api_routes():
        if name in CLIENT_MAY_USE or route.startswith("api/v1/portal/"):
            continue  # the portal itself: tests/portal/test_portal.py
        # The client's own party where a route names one (so a missing permission
        # check would answer 200), a random id elsewhere.
        own = str(party.pk) if route.startswith("api/v1/parties/") else None
        path = "/" + re.sub(r"<uuid:\w+>", lambda _m: own or str(uuid.uuid4()), route)  # noqa: B023
        for method in ("get", "post", "put", "patch", "delete"):
            r = getattr(api, method)(path, {}, **headers)
            if r.status_code not in (403, 404, 405):
                leaks.append(f"{method.upper()} {path} -> {r.status_code}")
    assert not leaks, leaks


# --- portal users of a client ----------------------------------------------------------


def _join_token() -> str:
    link = re.search(r"https://app\.example\.test/join\?\S+", str(mail.outbox[-1].body))
    assert link, mail.outbox[-1].body
    return parse_qs(urlparse(link.group(0)).query)["token"][0]


def test_invite_a_new_person_who_joins_as_the_clients_portal_user(
    api: APIClient, company: TenantFixture, party: Party, django_capture_on_commit_callbacks: Any
) -> None:
    owner = owner_member(company)
    with django_capture_on_commit_callbacks(execute=True):
        r = api.post(_portal_url(party), {"email": "Anna@Example.com"}, **_as(owner.access_token))
    assert r.status_code == 201, r.content
    assert r.json()["kind"] == "EMAIL_INVITATION"
    assert r.json()["status"] == "PENDING"
    assert r.json()["email"] == "anna@example.com"
    assert "as a client, to see your bills and payments online" in mail.outbox[-1].body

    # not among the business's own staff invitations
    staff = api.get("/api/v1/email-invitations", **_as(owner.access_token)).json()["results"]
    assert staff == []

    joined = api.post(
        "/api/v1/auth/join",
        {"token": _join_token(), "full_name": "Anna Kurian", "password": PASSWORD},
    )
    assert joined.status_code == 201, joined.content
    assert joined.json()["role"] == "CLIENT"
    principal = verify_access_token(joined.json()["access_token"])
    assert principal.amr == {"pwd", "email"}  # the link proved the inbox
    assert principal.party_id == party.pk

    rows = api.get(_portal_url(party), **_as(owner.access_token)).json()["results"]
    assert [(row["kind"], row["status"], row["full_name"]) for row in rows] == [
        ("MEMBER", "ACTIVE", "Anna Kurian")
    ]
    members = api.get("/api/v1/members", **_as(owner.access_token)).json()["results"]
    assert "anna@example.com" not in {m["email"] for m in members}


def test_invite_someone_with_an_account(
    api: APIClient, company: TenantFixture, party: Party
) -> None:
    owner = owner_member(company)
    person = make_user("Existing Person")
    r = api.post(_portal_url(party), {"email": person.email}, **_as(owner.access_token))
    assert r.status_code == 201, r.content
    assert (r.json()["kind"], r.json()["status"]) == ("MEMBER", "INVITED")

    # they see it among their invitations, as from the business
    from apps.accounts.services import ClientInfo, _start_session

    other = make_tenant("Their Own Co")
    with tenant_context(other.tenant_id, other.user_id):
        Membership.objects.create(tenant_id=other.tenant_id, user=person, role="OWNER")
    token = _start_session(
        user_id=person.pk,
        tenant_id=other.tenant_id,
        role="OWNER",
        amr=frozenset({"pwd", "otp"}),
        client=ClientInfo(),
    ).access_token
    mine = api.get("/api/v1/invitations", **_as(token)).json()["results"]
    assert [(i["legal_name"], i["role"]) for i in mine] == [("Nair Constructions", "CLIENT")]

    again = api.post(_portal_url(party), {"email": person.email}, **_as(owner.access_token))
    assert again.status_code == 409
    assert _code(again) == "already_invited"


def test_a_staff_member_or_another_clients_user_cannot_be_invited(
    api: APIClient, company: TenantFixture, party: Party
) -> None:
    owner = owner_member(company)
    accountant = add_member(company, "ACCOUNTANT")
    email = User.objects.get(pk=accountant.user_id).email
    r = api.post(_portal_url(party), {"email": email}, **_as(owner.access_token))
    assert (r.status_code, _code(r)) == (409, "already_member")

    other_party = make_party(company, "Other Client")
    client = add_client(company, other_party)
    email = User.objects.get(pk=client.user_id).email
    r = api.post(_portal_url(party), {"email": email}, **_as(owner.access_token))
    assert (r.status_code, _code(r)) == (409, "other_client")


def test_only_customers_get_portal_users(api: APIClient, company: TenantFixture) -> None:
    owner = owner_member(company)
    with tenant_context(company.tenant_id, company.user_id):
        vendor = Party.objects.create(
            display_name="Cement Supplier",
            gst_treatment="UNREGISTERED",
            is_customer=False,
            is_vendor=True,
            created_by_id=company.user_id,
        )
    r = api.post(_portal_url(vendor), {"email": "x@example.com"}, **_as(owner.access_token))
    assert (r.status_code, _code(r)) == (422, "not_a_client")


def test_revoking_a_portal_user_signs_them_out(
    api: APIClient, company: TenantFixture, party: Party
) -> None:
    owner = owner_member(company)
    client = add_client(company, party)
    assert api.get("/api/v1/invitations", **_as(client.access_token)).status_code == 200

    r = api.delete(f"{_portal_url(party)}/{client.membership_id}", **_as(owner.access_token))
    assert r.status_code == 204
    assert api.get("/api/v1/invitations", **_as(client.access_token)).status_code == 401
    assert not AuthSession.objects.filter(user_id=client.user_id, revoked_at__isnull=True).exists()
    assert api.get(_portal_url(party), **_as(owner.access_token)).json()["results"] == []
    # again: harmless; an unknown id: 404
    assert (
        api.delete(f"{_portal_url(party)}/{client.membership_id}", **_as(owner.access_token))
    ).status_code == 204
    assert (
        api.delete(f"{_portal_url(party)}/{uuid.uuid4()}", **_as(owner.access_token))
    ).status_code == 404


def test_portal_users_are_not_managed_as_members(
    api: APIClient, company: TenantFixture, party: Party
) -> None:
    owner = owner_member(company)
    client = add_client(company, party)
    url = f"/api/v1/members/{client.membership_id}"
    assert api.patch(url, {"role": "VIEWER"}, **_as(owner.access_token)).status_code == 404
    assert api.delete(url, **_as(owner.access_token)).status_code == 404
    r = api.post(
        "/api/v1/members", {"email": "x@example.com", "role": "CLIENT"}, **_as(owner.access_token)
    )
    assert r.status_code == 422  # CLIENT is not a staff role


def test_only_owners_and_admins_manage_portal_users(
    api: APIClient, company: TenantFixture, party: Party
) -> None:
    accountant = add_member(company, "ACCOUNTANT")
    assert api.get(_portal_url(party), **_as(accountant.access_token)).status_code == 403
    r = api.post(_portal_url(party), {"email": "x@example.com"}, **_as(accountant.access_token))
    assert r.status_code == 403


def test_portal_user_routes_reject_another_tenants_client(
    api: APIClient, company: TenantFixture, party: Party
) -> None:
    client = add_client(company, party)
    intruder = owner_member(make_tenant("Intruder Co"))
    url = _portal_url(party)
    assert api.get(url, **_as(intruder.access_token)).status_code == 404
    assert (
        api.post(url, {"email": "x@example.com"}, **_as(intruder.access_token)).status_code == 404
    )
    assert (
        api.delete(f"{url}/{client.membership_id}", **_as(intruder.access_token))
    ).status_code == 404
    with tenant_context(company.tenant_id, company.user_id):
        assert Membership.objects.get(pk=client.membership_id).status == "ACTIVE"
