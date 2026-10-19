"""Invite + accept: nobody joins a business without consenting."""

from collections.abc import Callable
from typing import Any

import pytest
from django.db import DatabaseError, connection, transaction
from rest_framework.test import APIClient

from apps.accounts.models import Membership, User
from apps.core.tenancy import tenant_context, user_context
from tests.factories import Member, TenantFixture, add_member, make_party, make_tenant, owner_member

from .conftest import Account, bearer

pytestmark = pytest.mark.django_db

MakeAccount = Callable[..., Account]


@pytest.fixture
def tenant() -> TenantFixture:
    return make_tenant("Inviting Builders")


@pytest.fixture
def owner(tenant: TenantFixture) -> Member:
    return owner_member(tenant)


def _invite(api: APIClient, actor: Member, email: str, role: str = "ACCOUNTANT") -> Any:
    return api.post(
        "/api/v1/members",
        {"email": email, "role": role},
        format="json",
        **bearer(actor.access_token),
    )


def _problem(response: Any) -> tuple[int, str]:
    return response.status_code, response.json()["code"]


def _invitations(api: APIClient, account: Account) -> list[dict[str, Any]]:
    response = api.get("/api/v1/invitations", **bearer(account.access))
    assert response.status_code == 200
    return list(response.json()["results"])


def test_invite_accept_then_switch_in(
    api: APIClient, tenant: TenantFixture, owner: Member, make_account: MakeAccount
) -> None:
    invitee = make_account("Invitee's Own Firm")
    invited = _invite(api, owner, invitee.email.upper(), "ACCOUNTANT")
    assert invited.status_code == 201
    assert invited.json()["status"] == "INVITED"

    [invitation] = _invitations(api, invitee)
    assert invitation["legal_name"] == "Inviting Builders"
    assert invitation["role"] == "ACCOUNTANT"
    assert invitation["invited_by_name"] == "Test User"

    # not a member yet: cannot switch in
    switch = {"tenant_id": str(tenant.tenant_id)}
    early = api.post("/api/v1/auth/switch-tenant", switch, format="json", **bearer(invitee.access))
    assert _problem(early) == (404, "not_found")

    accepted = api.post(f"/api/v1/invitations/{invitation['id']}/accept", **bearer(invitee.access))
    assert accepted.status_code == 200
    assert accepted.json() == {
        "id": str(tenant.tenant_id),
        "legal_name": "Inviting Builders",
        "role": "ACCOUNTANT",
    }
    assert _invitations(api, invitee) == []

    joined = api.post("/api/v1/auth/switch-tenant", switch, format="json", **bearer(invitee.access))
    assert joined.status_code == 200
    assert joined.json()["role"] == "ACCOUNTANT"


def test_decline(
    api: APIClient, tenant: TenantFixture, owner: Member, make_account: MakeAccount
) -> None:
    invitee = make_account()
    membership_id = _invite(api, owner, invitee.email).json()["id"]
    declined = api.post(f"/api/v1/invitations/{membership_id}/decline", **bearer(invitee.access))
    assert declined.status_code == 204
    with tenant_context(tenant.tenant_id, tenant.user_id):
        assert Membership.objects.get(pk=membership_id).status == "REVOKED"
    # a declined (revoked) person can be invited again
    assert _invite(api, owner, invitee.email).status_code == 201


def test_only_the_invitee_can_respond_and_only_once(
    api: APIClient, tenant: TenantFixture, owner: Member, make_account: MakeAccount
) -> None:
    invitee, stranger = make_account(), make_account()
    membership_id = _invite(api, owner, invitee.email).json()["id"]
    url = f"/api/v1/invitations/{membership_id}/accept"
    assert _problem(api.post(url, **bearer(stranger.access))) == (404, "not_found")
    assert api.post(url, **bearer(invitee.access)).status_code == 200
    assert _problem(api.post(url, **bearer(invitee.access))) == (404, "not_found")


def test_invite_errors(
    api: APIClient, tenant: TenantFixture, owner: Member, make_account: MakeAccount
) -> None:
    invitee = make_account()
    nobody = _invite(api, owner, "no-such-person@example.com")
    assert _problem(nobody) == (422, "validation_error")
    assert nobody.json()["errors"][0]["code"] == "no_account"

    assert _invite(api, owner, invitee.email).status_code == 201
    assert _problem(_invite(api, owner, invitee.email)) == (409, "already_invited")

    accountant = add_member(tenant, "ACCOUNTANT")
    accountant_email = User.objects.get(pk=accountant.user_id).email
    assert _problem(_invite(api, owner, str(accountant_email))) == (409, "already_member")


def test_who_may_invite_whom(
    api: APIClient, tenant: TenantFixture, make_account: MakeAccount
) -> None:
    invitee = make_account()
    admin = add_member(tenant, "ADMIN")
    accountant = add_member(tenant, "ACCOUNTANT")
    assert _problem(_invite(api, admin, invitee.email, "OWNER")) == (403, "owner_protected")
    assert _problem(_invite(api, accountant, invitee.email)) == (403, "permission_denied")
    assert _invite(api, admin, invitee.email, "SITE_ENGINEER").status_code == 201


def test_invitee_sees_only_the_inviters_name_not_its_data(
    api: APIClient, tenant: TenantFixture, owner: Member, make_account: MakeAccount
) -> None:
    make_party(tenant, "Inviter's client")
    invitee = make_account()
    _invite(api, owner, invitee.email)
    user = User.objects.get(email=invitee.email)
    with user_context(user.pk), connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM parties")  # RLS: no tenant, no rows
        assert cursor.fetchone() == (0,)
        assert Membership.objects.filter(tenant_id=tenant.tenant_id).count() == 1  # own row only


def test_respond_to_invitation_restores_the_tenant_context(
    api: APIClient, tenant: TenantFixture, owner: Member, make_account: MakeAccount
) -> None:
    invitee = make_account()
    membership_id = _invite(api, owner, invitee.email).json()["id"]
    user = User.objects.get(email=invitee.email)
    with tenant_context(invitee.tenant_id, user.pk), connection.cursor() as cursor:
        cursor.execute("SELECT respond_to_invitation(%s, true)", [membership_id])
        cursor.execute("SELECT app_current_tenant()::text")
        assert cursor.fetchone() == (invitee.tenant_id,)


def test_respond_to_invitation_cannot_touch_other_memberships(
    tenant: TenantFixture, owner: Member
) -> None:
    """The DB function only accepts the caller's own INVITED membership."""
    accountant = add_member(tenant, "ACCOUNTANT")  # ACTIVE, not invited
    with user_context(accountant.user_id), connection.cursor() as cursor:
        with pytest.raises(DatabaseError), transaction.atomic():
            cursor.execute("SELECT respond_to_invitation(%s, true)", [owner.membership_id])
        with pytest.raises(DatabaseError), transaction.atomic():
            cursor.execute("SELECT respond_to_invitation(%s, true)", [accountant.membership_id])
