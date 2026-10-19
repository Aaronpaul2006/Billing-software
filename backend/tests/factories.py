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
            gstin=f"{state_code}ABCDE1234F1Z5",
            state_code=state_code,
            legal_name=name,
            address={"line1": "1 Main Road"},
            is_default=True,
        )
    return TenantFixture(tenant_id=tenant_id, user_id=user.id, registration_id=registration.id)


def make_party(t: TenantFixture, name: str = "Client Ltd") -> Party:
    with tenant_context(t.tenant_id, t.user_id):
        return Party.objects.create(
            tenant_id=t.tenant_id,
            display_name=name,
            gst_treatment=Party.GstTreatment.UNREGISTERED,
            created_by_id=t.user_id,
        )
