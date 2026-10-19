"""Minimal data builders for tests. Every call uses fresh ids."""

import uuid
from dataclasses import dataclass

from apps.accounts.models import Membership, Role, User
from apps.core.tenancy import tenant_context
from apps.parties.models import Party
from apps.tenants.models import GstRegistration, Tenant

UNUSABLE_PASSWORD = "!"


@dataclass(frozen=True)
class TenantFixture:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    registration_id: uuid.UUID


def make_user(name: str = "Test User") -> User:
    uid = uuid.uuid7()
    return User.objects.create(
        id=uid,
        email=f"{uid.hex}@example.com",
        password_hash=UNUSABLE_PASSWORD,
        full_name=name,
    )


def make_tenant(name: str = "Acme Builders", state_code: str = "32") -> TenantFixture:
    """A tenant with an OWNER and a REGULAR GST registration.

    Creating a tenant follows db/schema.sql §8: the id is chosen first and
    set as the context, then the tenant row and membership are inserted.
    """
    user = make_user()
    tenant_id = uuid.uuid7()
    with tenant_context(tenant_id, user.id):
        Tenant.objects.create(id=tenant_id, legal_name=name)
        Membership.objects.create(tenant_id=tenant_id, user=user, role=Role.OWNER)
        registration = GstRegistration.objects.create(
            tenant_id=tenant_id,
            registration_type=GstRegistration.RegistrationType.REGULAR,
            gstin=gstin(state_code, entity="9"),
            state_code=state_code,
            legal_name=name,
            address={
                "line1": "1 Main Road",
                "city": "Kochi",
                "state_code": state_code,
                "pincode": "682016",
            },
            is_default=True,
        )
    return TenantFixture(tenant_id=tenant_id, user_id=user.id, registration_id=registration.id)


def make_party(t: TenantFixture, name: str = "Client Ltd") -> Party:
    with tenant_context(t.tenant_id, t.user_id):
        party: Party = Party.objects.create(
            tenant_id=t.tenant_id,
            display_name=name,
            gst_treatment=Party.GstTreatment.UNREGISTERED,
            created_by_id=t.user_id,
        )
        return party


@dataclass(frozen=True)
class Member:
    user_id: uuid.UUID
    membership_id: uuid.UUID
    access_token: str
    refresh_token: str


def add_member(t: TenantFixture, role: str, *, with_mfa: bool = True) -> Member:
    """A user with `role` in tenant `t` and a live session (amr has otp if with_mfa)."""
    from apps.accounts.services import ClientInfo, _start_session

    user = make_user(f"{role.title()} User")
    with tenant_context(t.tenant_id, t.user_id):
        membership = Membership.objects.create(
            tenant_id=t.tenant_id, user=user, role=role, invited_by_id=t.user_id
        )
    tokens = _start_session(
        user_id=user.id,
        tenant_id=t.tenant_id,
        role=role,
        amr=frozenset({"pwd", "otp"} if with_mfa else {"pwd"}),
        client=ClientInfo(),
    )
    return Member(user.id, membership.id, tokens.access_token, tokens.refresh_token)


def owner_member(t: TenantFixture) -> Member:
    """A session for the tenant's founding OWNER (from make_tenant)."""
    from apps.accounts.services import ClientInfo, _start_session

    with tenant_context(t.tenant_id, t.user_id):
        membership = Membership.objects.get(user_id=t.user_id)
    tokens = _start_session(
        user_id=t.user_id,
        tenant_id=t.tenant_id,
        role=Role.OWNER,
        amr=frozenset({"pwd", "otp"}),
        client=ClientInfo(),
    )
    return Member(t.user_id, membership.id, tokens.access_token, tokens.refresh_token)


def gstin(state: str = "32", pan: str = "AAACA1234A", entity: str = "1") -> str:
    """A GSTIN with a correct check digit (apps.core.india)."""
    from apps.core.india import gstin_check_char

    first14 = f"{state}{pan}{entity}Z"
    return first14 + gstin_check_char(first14)


def session_for(tenant_id: uuid.UUID, user_id: uuid.UUID, role: str = "OWNER") -> str:
    """An access token for an existing member (amr includes otp)."""
    from apps.accounts.services import ClientInfo, _start_session

    return _start_session(
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        amr=frozenset({"pwd", "otp"}),
        client=ClientInfo(),
    ).access_token
