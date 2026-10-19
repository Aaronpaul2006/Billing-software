"""Member management within the current tenant (docs/01-architecture.md §3).

Rules beyond the role matrix:
* nobody changes or revokes their own membership;
* an ADMIN cannot touch an OWNER and cannot make anyone OWNER;
* a tenant always keeps at least one active OWNER;
* revoking a member, or changing their role, signs out their sessions for
  this tenant at once (the next request with an old token gets 401);
* new members are invited (status INVITED) and join only when they accept.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from django.db import DatabaseError, IntegrityError, connection, transaction
from django.utils import timezone

from apps.core.errors import Conflict, Forbidden, Invalid, NotFound
from apps.core.permissions import ADMIN, OWNER, require
from apps.core.tenancy import Principal, user_context
from apps.tenants.models import Tenant

from .models import AuthSession, Membership, MembershipStatus, User, UserStatus
from .services import TenantSummary, active_memberships, normalise_email

security_log = logging.getLogger("security")
NO_DATA_FOUND = "P0002"


@dataclass(frozen=True)
class MemberInfo:
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    full_name: str
    role: str
    status: str
    invited_by: uuid.UUID | None
    created_at: datetime


def _info(membership: Membership, user: User) -> MemberInfo:
    return MemberInfo(
        id=membership.pk,
        user_id=user.pk,
        email=str(user.email),
        full_name=user.full_name,
        role=membership.role,
        status=membership.status,
        invited_by=membership.invited_by_id,
        created_at=membership.created_at,
    )


def list_members(principal: Principal) -> list[MemberInfo]:
    require(principal, "members.manage")
    memberships = list(
        Membership.objects.filter(tenant_id=principal.tenant_id).order_by("created_at")
    )
    users = User.objects.in_bulk([m.user_id for m in memberships])
    return [_info(m, users[m.user_id]) for m in memberships]


def _locked_member(principal: Principal, membership_id: uuid.UUID) -> Membership:
    # RLS already limits this to the principal's tenant; the explicit filter
    # documents it. Another tenant's membership is simply not found (404).
    membership = (
        Membership.objects.select_for_update()
        .filter(id=membership_id, tenant_id=principal.tenant_id)
        .first()
    )
    if membership is None:
        raise NotFound
    return membership


def _check_may_modify(principal: Principal, target: Membership, new_role: str | None) -> None:
    if target.user_id == principal.user_id:
        raise Forbidden("You cannot change your own membership.", code="cannot_modify_self")
    if principal.role == ADMIN and (target.role == OWNER or new_role == OWNER):
        raise Forbidden("Only an owner can change owners.", code="owner_protected")


def _ensure_another_owner(target: Membership) -> None:
    """The tenant must keep an active OWNER besides `target` (rows locked)."""
    others = (
        Membership.objects.select_for_update()
        .filter(tenant_id=target.tenant_id, role=OWNER, status=MembershipStatus.ACTIVE)
        .exclude(pk=target.pk)
    )
    if not list(others):
        raise Conflict("A business must keep at least one owner.", code="last_owner")


def _end_sessions(target: Membership) -> None:
    AuthSession.objects.filter(
        user_id=target.user_id, tenant_id=target.tenant_id, revoked_at__isnull=True
    ).update(revoked_at=timezone.now())


def change_role(principal: Principal, membership_id: uuid.UUID, role: str) -> MemberInfo:
    require(principal, "members.manage")
    with transaction.atomic():
        target = _locked_member(principal, membership_id)
        if target.status == MembershipStatus.REVOKED:
            raise Conflict("This member has been removed.", code="member_revoked")
        _check_may_modify(principal, target, role)
        if target.role != role:
            if target.role == OWNER:
                _ensure_another_owner(target)
            target.role = role
            target.save(update_fields=["role", "updated_at"])
            _end_sessions(target)  # their tokens carry the old role
    return _info(target, User.objects.get(pk=target.user_id))


def revoke(principal: Principal, membership_id: uuid.UUID) -> None:
    """Remove a member (status REVOKED; memberships are never deleted)."""
    require(principal, "members.manage")
    with transaction.atomic():
        target = _locked_member(principal, membership_id)
        if target.status == MembershipStatus.REVOKED:
            return  # idempotent
        _check_may_modify(principal, target, None)
        if target.role == OWNER:
            _ensure_another_owner(target)
        target.status = MembershipStatus.REVOKED
        target.save(update_fields=["status", "updated_at"])
        _end_sessions(target)


# --- invitations ------------------------------------------------------------------


def invite(principal: Principal, email: str, role: str) -> MemberInfo:
    """Invite an existing account (status INVITED until they accept)."""
    require(principal, "members.manage")
    if principal.role == ADMIN and role == OWNER:
        raise Forbidden("Only an owner can invite an owner.", code="owner_protected")
    user = User.objects.filter(email=normalise_email(email), status=UserStatus.ACTIVE).first()
    if user is None:
        raise Invalid(
            "email",
            "No account uses this email. Ask them to sign up first.",
            code="no_account",
        )
    try:
        with transaction.atomic():
            membership = (
                Membership.objects.select_for_update()
                .filter(tenant_id=principal.tenant_id, user_id=user.pk)
                .first()
            )
            if membership is None:
                membership = Membership.objects.create(
                    tenant_id=principal.tenant_id,
                    user=user,
                    role=role,
                    status=MembershipStatus.INVITED,
                    invited_by_id=principal.user_id,
                )
            elif membership.status == MembershipStatus.ACTIVE:
                raise Conflict("This person is already a member.", code="already_member")
            elif membership.status == MembershipStatus.INVITED:
                raise Conflict("This person has already been invited.", code="already_invited")
            else:  # REVOKED earlier: invite again
                membership.status = MembershipStatus.INVITED
                membership.role = role
                membership.invited_by_id = principal.user_id
                membership.save(update_fields=["status", "role", "invited_by", "updated_at"])
    except IntegrityError as exc:  # a concurrent invite created it first
        raise Conflict("This person has already been invited.", code="already_invited") from exc
    security_log.info(
        "member_invited tenant=%s user=%s role=%s by=%s",
        principal.tenant_id,
        user.pk,
        role,
        principal.user_id,
    )
    return _info(membership, user)


@dataclass(frozen=True)
class Invitation:
    id: uuid.UUID
    tenant_id: uuid.UUID
    legal_name: str
    role: str
    invited_by_name: str | None
    invited_at: datetime


def my_invitations(principal: Principal) -> list[Invitation]:
    """Pending invitations for the signed-in user, in any tenant.

    Visible through RLS: the user's own memberships (membership_own_read)
    and the inviting tenants' rows (tenant_member_read includes INVITED).
    """
    pending = list(
        Membership.objects.filter(
            user_id=principal.user_id, status=MembershipStatus.INVITED
        ).order_by("-updated_at")
    )
    tenants = Tenant.objects.in_bulk([m.tenant_id for m in pending])
    inviters = User.objects.in_bulk([m.invited_by_id for m in pending if m.invited_by_id])
    return [
        Invitation(
            id=m.pk,
            tenant_id=m.tenant_id,
            legal_name=tenants[m.tenant_id].legal_name,
            role=m.role,
            invited_by_name=(
                inviters[m.invited_by_id].full_name if m.invited_by_id in inviters else None
            ),
            invited_at=m.updated_at,
        )
        for m in pending
        if m.tenant_id in tenants
    ]


def respond(principal: Principal, membership_id: uuid.UUID, *, accept: bool) -> uuid.UUID:
    """Accept or decline one's own pending invitation; returns the tenant id.

    Goes through the database function respond_to_invitation(), the only path
    that may update a membership of a tenant the user is not signed in to.
    """
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SELECT respond_to_invitation(%s, %s)", [membership_id, accept])
            row = cursor.fetchone()
    except DatabaseError as exc:
        if getattr(exc.__cause__, "sqlstate", None) == NO_DATA_FOUND:
            raise NotFound from exc
        raise
    if row is None:  # respond_to_invitation() always returns the tenant id
        raise RuntimeError("respond_to_invitation returned no row")
    security_log.info(
        "invitation_%s user=%s membership=%s",
        "accepted" if accept else "declined",
        principal.user_id,
        membership_id,
    )
    return uuid.UUID(str(row[0]))


def my_tenants(principal: Principal) -> list[TenantSummary]:
    """Tenants the signed-in user is an active member of (for responses)."""
    with user_context(principal.user_id):
        return [
            TenantSummary(t.id, t.legal_name, m.role)
            for m, t in active_memberships(principal.user_id)
        ]
