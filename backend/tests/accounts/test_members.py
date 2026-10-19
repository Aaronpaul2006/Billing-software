"""Member management: who may change whom, and that changes bite immediately."""

from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Membership, MembershipStatus
from apps.core.tenancy import tenant_context
from tests.factories import Member, TenantFixture, add_member, make_tenant, owner_member

from .conftest import bearer

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant() -> TenantFixture:
    return make_tenant("Members Co")


@pytest.fixture
def owner(tenant: TenantFixture) -> Member:
    return owner_member(tenant)


def _patch(api: APIClient, actor: Member, target: Member, role: str) -> Any:
    return api.patch(
        f"/api/v1/members/{target.membership_id}",
        {"role": role},
        format="json",
        **bearer(actor.access_token),
    )


def _delete(api: APIClient, actor: Member, target: Member) -> Any:
    return api.delete(f"/api/v1/members/{target.membership_id}", **bearer(actor.access_token))


def _problem(response: Any) -> tuple[int, str]:
    return response.status_code, response.json()["code"]


def _alive(api: APIClient, member: Member) -> bool:
    return bool(api.get("/api/v1/me", **bearer(member.access_token)).status_code == 200)


def test_owner_lists_members(api: APIClient, tenant: TenantFixture, owner: Member) -> None:
    accountant = add_member(tenant, "ACCOUNTANT")
    response = api.get("/api/v1/members", **bearer(owner.access_token))
    assert response.status_code == 200
    roles = {m["id"]: m["role"] for m in response.json()["results"]}
    assert roles == {str(owner.membership_id): "OWNER", str(accountant.membership_id): "ACCOUNTANT"}


@pytest.mark.parametrize("role", ["ACCOUNTANT", "SITE_ENGINEER", "VIEWER"])
def test_other_roles_cannot_manage_members(
    api: APIClient, tenant: TenantFixture, owner: Member, role: str
) -> None:
    member = add_member(tenant, role)
    assert _problem(api.get("/api/v1/members", **bearer(member.access_token))) == (
        403,
        "permission_denied",
    )
    assert _problem(_patch(api, member, owner, "VIEWER")) == (403, "permission_denied")


def test_admin_without_mfa_is_blocked(api: APIClient, tenant: TenantFixture) -> None:
    admin = add_member(tenant, "ADMIN", with_mfa=False)
    assert _problem(api.get("/api/v1/members", **bearer(admin.access_token))) == (
        403,
        "mfa_enrollment_required",
    )


def test_admin_changes_a_role_and_the_member_is_signed_out(
    api: APIClient, tenant: TenantFixture
) -> None:
    admin = add_member(tenant, "ADMIN")
    accountant = add_member(tenant, "ACCOUNTANT")
    response = _patch(api, admin, accountant, "VIEWER")
    assert response.status_code == 200
    assert response.json()["role"] == "VIEWER"
    # their token still said ACCOUNTANT: it must stop working now
    assert not _alive(api, accountant)
    assert _alive(api, admin)


def test_admin_cannot_touch_owners(api: APIClient, tenant: TenantFixture, owner: Member) -> None:
    admin = add_member(tenant, "ADMIN")
    viewer = add_member(tenant, "VIEWER")
    assert _problem(_patch(api, admin, owner, "VIEWER")) == (403, "owner_protected")
    assert _problem(_delete(api, admin, owner)) == (403, "owner_protected")
    assert _problem(_patch(api, admin, viewer, "OWNER")) == (403, "owner_protected")
    assert _alive(api, owner)


def test_nobody_modifies_their_own_membership(
    api: APIClient, tenant: TenantFixture, owner: Member
) -> None:
    assert _problem(_patch(api, owner, owner, "VIEWER")) == (403, "cannot_modify_self")
    assert _problem(_delete(api, owner, owner)) == (403, "cannot_modify_self")


def test_owner_can_appoint_and_be_replaced_by_another_owner(
    api: APIClient, tenant: TenantFixture, owner: Member
) -> None:
    admin = add_member(tenant, "ADMIN")
    assert _patch(api, owner, admin, "OWNER").status_code == 200
    # the promoted member signs in again (sessions ended on role change)
    new_owner = owner_member_for(tenant, admin)
    assert _patch(api, new_owner, owner, "ADMIN").status_code == 200


def owner_member_for(tenant: TenantFixture, member: Member) -> Member:
    from apps.accounts.services import ClientInfo, _start_session

    tokens = _start_session(
        user_id=member.user_id,
        tenant_id=tenant.tenant_id,
        role="OWNER",
        amr=frozenset({"pwd", "otp"}),
        client=ClientInfo(),
    )
    return Member(member.user_id, member.membership_id, tokens.access_token, tokens.refresh_token)


def test_last_owner_is_protected(api: APIClient, tenant: TenantFixture, owner: Member) -> None:
    second = add_member(tenant, "OWNER")
    # the first owner was removed behind the scenes but still holds a token
    with tenant_context(tenant.tenant_id, tenant.user_id):
        Membership.objects.filter(pk=owner.membership_id).update(status=MembershipStatus.REVOKED)
    assert _problem(_patch(api, owner, second, "ADMIN")) == (409, "last_owner")
    assert _problem(_delete(api, owner, second)) == (409, "last_owner")


def test_revoke_ends_access_immediately_and_is_idempotent(
    api: APIClient, tenant: TenantFixture, owner: Member
) -> None:
    engineer = add_member(tenant, "SITE_ENGINEER")
    assert _alive(api, engineer)
    assert _delete(api, owner, engineer).status_code == 204
    assert not _alive(api, engineer)
    refresh = api.post(
        "/api/v1/auth/token/refresh", {"refresh_token": engineer.refresh_token}, format="json"
    )
    assert refresh.status_code == 401
    with tenant_context(tenant.tenant_id, tenant.user_id):
        assert Membership.objects.get(pk=engineer.membership_id).status == "REVOKED"
    assert _delete(api, owner, engineer).status_code == 204  # again: no-op
    assert _problem(_patch(api, owner, engineer, "VIEWER")) == (409, "member_revoked")


def test_another_tenants_member_is_not_found(api: APIClient, tenant: TenantFixture) -> None:
    other_tenant = make_tenant("Other Co")
    their_member = add_member(other_tenant, "ACCOUNTANT")
    my_owner = owner_member(tenant)
    assert _problem(_patch(api, my_owner, their_member, "VIEWER")) == (404, "not_found")
    assert _problem(_delete(api, my_owner, their_member)) == (404, "not_found")
    assert _alive(api, their_member)


def test_invalid_role_is_rejected(api: APIClient, tenant: TenantFixture, owner: Member) -> None:
    viewer = add_member(tenant, "VIEWER")
    assert _problem(_patch(api, owner, viewer, "SUPERUSER")) == (422, "validation_error")
