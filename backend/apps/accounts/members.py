"""Member management within the current tenant (docs/01-architecture.md §3).

Rules beyond the role matrix:
* nobody changes or revokes their own membership;
* an ADMIN cannot touch an OWNER and cannot make anyone OWNER;
* a tenant always keeps at least one active OWNER;
* revoking a member, or changing their role, signs out their sessions for
  this tenant at once (the next request with an old token gets 401).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from apps.core.errors import Conflict, Forbidden, NotFound
from apps.core.permissions import ADMIN, OWNER, require
from apps.core.tenancy import Principal

from .models import AuthSession, Membership, MembershipStatus, User


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
