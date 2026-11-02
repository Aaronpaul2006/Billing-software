"""Client-portal users of one client (party), managed by OWNER / ADMIN (W.5).

A portal user is a membership with role CLIENT naming the party; the
database then limits their sessions to that client's issued bills, payments
and BOQ progress (db/schema.sql §8, client_scope). Several people per client
are allowed.

Inviting an address that has an account adds an INVITED membership, accepted
from the invitations banner; any other address gets an email invitation whose
link creates the account (apps.accounts.email_invitations). Both are listed
here, and either can be revoked. Signing in then needs a code emailed each
time, unless the person uses an authenticator app.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.errors import Conflict, Invalid, NotFound
from apps.core.permissions import require
from apps.core.queries import get_or_404
from apps.core.tenancy import Principal
from apps.parties.models import Party

from . import email_invitations
from .members import _end_sessions
from .models import (
    EmailInvitation,
    EmailInvitationStatus,
    Membership,
    MembershipStatus,
    Role,
    User,
    UserStatus,
)
from .services import normalise_email

security_log = logging.getLogger("security")


@dataclass(frozen=True)
class PortalUser:
    id: uuid.UUID  # the membership or the email invitation
    kind: str  # "MEMBER" (has an account) | "EMAIL_INVITATION" (signs up through the link)
    email: str
    full_name: str | None
    status: str  # ACTIVE | INVITED (member), PENDING (email invitation)
    created_at: datetime
    expires_at: datetime | None  # email invitations only


def _member(m: Membership, user: User) -> PortalUser:
    return PortalUser(
        id=m.pk,
        kind="MEMBER",
        email=str(user.email),
        full_name=user.full_name,
        status=m.status,
        created_at=m.created_at,
        expires_at=None,
    )


def _invitation(i: EmailInvitation) -> PortalUser:
    return PortalUser(
        id=i.pk,
        kind="EMAIL_INVITATION",
        email=str(i.email),
        full_name=None,
        status=i.status,
        created_at=i.created_at,
        expires_at=i.expires_at,
    )


def _party(principal: Principal, party_id: uuid.UUID) -> Party:
    require(principal, "members.manage")
    party: Party = get_or_404(Party, party_id)
    return party


def list_portal_users(principal: Principal, party_id: uuid.UUID) -> list[PortalUser]:
    party = _party(principal, party_id)
    memberships = list(
        Membership.objects.filter(
            party=party, status__in=[MembershipStatus.ACTIVE, MembershipStatus.INVITED]
        ).order_by("created_at")
    )
    users = User.objects.in_bulk([m.user_id for m in memberships])
    invitations = EmailInvitation.objects.filter(
        party=party, status=EmailInvitationStatus.PENDING
    ).order_by("created_at")
    return [_member(m, users[m.user_id]) for m in memberships] + [
        _invitation(i) for i in invitations
    ]


def invite(principal: Principal, party_id: uuid.UUID, email: str) -> PortalUser:
    party = _party(principal, party_id)
    if not party.is_customer:
        raise Invalid("party_id", "Only clients can use the portal.", code="not_a_client")
    email = normalise_email(email)
    user = User.objects.filter(email=email).first()
    if user is not None and user.status != UserStatus.ACTIVE:
        raise Invalid("email", "This account is not active.", code="account_inactive")
    try:
        with transaction.atomic():
            if user is None:
                invitation = EmailInvitation.objects.create(
                    email=email, role=Role.CLIENT, party=party, invited_by_id=principal.user_id
                )
                email_invitations._send_after_commit(invitation)
                result = _invitation(EmailInvitation.objects.get(pk=invitation.pk))
            else:
                result = _member(_invite_member(principal, party, user), user)
    except IntegrityError as exc:  # a concurrent invitation of the same address won
        raise Conflict("This email has already been invited.", code="already_invited") from exc
    security_log.info(
        "portal_user_invited tenant=%s party=%s %s=%s by=%s",
        principal.tenant_id,
        party.pk,
        result.kind.lower(),
        result.id,
        principal.user_id,
    )
    return result


def _invite_member(principal: Principal, party: Party, user: User) -> Membership:
    membership = (
        Membership.objects.select_for_update()
        .filter(tenant_id=principal.tenant_id, user_id=user.pk)
        .first()
    )
    if membership is None:
        return Membership.objects.create(
            tenant_id=principal.tenant_id,
            user=user,
            role=Role.CLIENT,
            party=party,
            status=MembershipStatus.INVITED,
            invited_by_id=principal.user_id,
        )
    if membership.status != MembershipStatus.REVOKED:
        if membership.party_id is None:
            raise Conflict("This person is a member of your business.", code="already_member")
        if membership.party_id != party.pk:
            raise Conflict("This person uses the portal for another client.", code="other_client")
        raise Conflict("This person already has portal access.", code="already_invited")
    # Removed earlier (as staff or as a client): invite again, as this client.
    membership.status = MembershipStatus.INVITED
    membership.role = Role.CLIENT
    membership.party = party
    membership.invited_by_id = principal.user_id
    membership.save(update_fields=["status", "role", "party", "invited_by", "updated_at"])
    return membership


def revoke(principal: Principal, party_id: uuid.UUID, portal_user_id: uuid.UUID) -> None:
    """End portal access at once (signs out their sessions) or withdraw the
    email invitation. Repeating it is harmless."""
    party = _party(principal, party_id)
    with transaction.atomic():
        membership = (
            Membership.objects.select_for_update().filter(pk=portal_user_id, party=party).first()
        )
        if membership is not None:
            if membership.status != MembershipStatus.REVOKED:
                membership.status = MembershipStatus.REVOKED
                membership.save(update_fields=["status", "updated_at"])
                _end_sessions(membership)
        else:
            invitation = (
                EmailInvitation.objects.select_for_update()
                .filter(pk=portal_user_id, party=party)
                .first()
            )
            if invitation is None:
                raise NotFound
            if invitation.status == EmailInvitationStatus.PENDING:
                EmailInvitation.objects.filter(pk=invitation.pk).update(
                    status=EmailInvitationStatus.REVOKED, updated_at=timezone.now()
                )
    security_log.info(
        "portal_user_revoked party=%s id=%s by=%s", party.pk, portal_user_id, principal.user_id
    )
