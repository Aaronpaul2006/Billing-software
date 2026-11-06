"""Invitations by email, for people with no account yet (docs/02-api-design.md §3).

An OWNER / ADMIN invites an address; the email carries a signed link (7 days)
to /join, where the person names themselves, chooses a password and lands in
the company with the invited role (their email counts as confirmed: the link
proves the inbox). Signing up the normal way instead also works: the pending
invitations become INVITED memberships (claim_email_invitations()).

The link names the invitation and its tenant; it is signed by us, so the join
endpoint may open that tenant's context from it, like an access token's tid.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core import signing
from django.core.mail import send_mail
from django.db import IntegrityError, connection, transaction
from django.template.loader import render_to_string
from django.utils import timezone

from apps.core.errors import Conflict, Forbidden, Invalid
from apps.core.permissions import ADMIN, OWNER, require
from apps.core.queries import get_or_404
from apps.core.tenancy import Principal, tenant_context
from apps.notifications import tasks as notify
from apps.tenants.models import Tenant, TenantStatus

from . import emails
from .models import (
    EmailInvitation,
    EmailInvitationStatus,
    Membership,
    MembershipStatus,
    User,
)
from .services import (
    ClientInfo,
    SessionTokens,
    TenantSummary,
    _check_new_password,
    _start_session,
    _with_tenants,
    normalise_email,
)

security_log = logging.getLogger("security")
INVITE_SALT = "accounts.email-invitation"
PENDING = EmailInvitationStatus.PENDING


def _ttl() -> timedelta:
    return timedelta(seconds=settings.EMAIL_INVITATION_MAX_AGE)


def make_token(invitation: EmailInvitation) -> str:
    return signing.dumps(
        {"u": str(invitation.pk), "t": str(invitation.tenant_id), "e": str(invitation.email)},
        salt=INVITE_SALT,
    )


def read_token(token: str) -> tuple[uuid.UUID, uuid.UUID, str]:
    """(invitation id, tenant id, email). Raises LinkInvalid / LinkExpired."""
    invitation_id, tenant_id, email = emails._payload(
        token, INVITE_SALT, settings.EMAIL_INVITATION_MAX_AGE, "t", "e"
    )
    try:
        return invitation_id, uuid.UUID(tenant_id), email
    except ValueError as exc:
        raise emails.link_invalid() from exc


def _send_after_commit(invitation: EmailInvitation) -> None:
    from .tasks import send_invitation_email_task

    tenant_id, invitation_id = str(invitation.tenant_id), str(invitation.pk)
    transaction.on_commit(
        lambda: send_invitation_email_task.delay(tenant_id, invitation_id), robust=True
    )


def send_invitation_email(invitation_id: uuid.UUID) -> bool:
    """Build and send the invitation. Call inside the tenant's context."""
    invitation = EmailInvitation.objects.filter(pk=invitation_id, status=PENDING).first()
    if invitation is None:
        return False
    tenant = Tenant.objects.get(pk=invitation.tenant_id)
    inviter = User.objects.get(pk=invitation.invited_by_id)
    body = render_to_string(
        "accounts/email/invitation.txt",
        {
            "inviter": inviter.full_name,
            "company": tenant.legal_name,
            "role": (
                "a client, to see your bills and payments online"
                if invitation.party_id
                else invitation.role.replace("_", " ").lower()
            ),
            "link": emails._link("join", make_token(invitation)),
            "days": settings.EMAIL_INVITATION_MAX_AGE // 86400,
        },
    )
    send_mail(
        f"{inviter.full_name} invited you to {tenant.legal_name}", body, None, [invitation.email]
    )
    return True


# --- managing invitations (OWNER / ADMIN, in their tenant) --------------------------------


def _check_role(principal: Principal, role: str) -> None:
    require(principal, "members.manage")
    if principal.role == ADMIN and role == OWNER:
        raise Forbidden("Only an owner can invite an owner.", code="owner_protected")


def create(principal: Principal, email: str, role: str) -> EmailInvitation:
    _check_role(principal, role)
    email = normalise_email(email)
    if User.objects.filter(email=email).exists():
        raise Invalid(
            "email",
            "This person has an account: invite them as a member instead.",
            code="has_account",
        )
    try:
        with transaction.atomic():
            invitation = EmailInvitation.objects.create(
                email=email, role=role, invited_by_id=principal.user_id
            )
            _send_after_commit(invitation)
    except IntegrityError as exc:
        raise Conflict("This email has already been invited.", code="already_invited") from exc
    security_log.info(
        "email_invited tenant=%s invitation=%s role=%s by=%s",
        principal.tenant_id,
        invitation.pk,
        role,
        principal.user_id,
    )
    created: EmailInvitation = EmailInvitation.objects.get(pk=invitation.pk)
    return created  # with the database's expires_at


def pending(principal: Principal) -> list[EmailInvitation]:
    """Staff invitations; client-portal ones are listed under their client."""
    require(principal, "members.manage")
    return list(
        EmailInvitation.objects.filter(status=PENDING, party__isnull=True).order_by("created_at")
    )


def _pending(principal: Principal, invitation_id: uuid.UUID) -> EmailInvitation:
    require(principal, "members.manage")
    invitation: EmailInvitation = get_or_404(EmailInvitation, invitation_id, for_update=True)
    if invitation.status != PENDING:
        raise Conflict("This invitation is no longer open.", code="not_pending")
    if principal.role == ADMIN and invitation.role == OWNER:
        raise Forbidden("Only an owner can change an owner's invitation.", code="owner_protected")
    return invitation


def revoke(principal: Principal, invitation_id: uuid.UUID) -> None:
    with transaction.atomic():
        invitation = _pending(principal, invitation_id)
        EmailInvitation.objects.filter(pk=invitation.pk).update(
            status=EmailInvitationStatus.REVOKED, updated_at=timezone.now()
        )
    security_log.info(
        "email_invitation_revoked invitation=%s by=%s", invitation_id, principal.user_id
    )


def resend(principal: Principal, invitation_id: uuid.UUID) -> EmailInvitation:
    """Send the email again; the link works for another 7 days from now."""
    with transaction.atomic():
        invitation = _pending(principal, invitation_id)
        EmailInvitation.objects.filter(pk=invitation.pk).update(
            expires_at=timezone.now() + _ttl(), updated_at=timezone.now()
        )
        _send_after_commit(invitation)
    renewed: EmailInvitation = EmailInvitation.objects.get(pk=invitation_id)
    return renewed


# --- joining through the link (public) ----------------------------------------------------


@dataclass(frozen=True)
class JoinDetails:
    email: str
    legal_name: str
    role: str
    invited_by_name: str
    expires_at: datetime


def _open_invitation(invitation_id: uuid.UUID, email: str, *, lock: bool) -> EmailInvitation:
    """The pending invitation the link names. Call inside its tenant's context."""
    queryset = EmailInvitation.objects.select_for_update() if lock else EmailInvitation.objects
    invitation: EmailInvitation | None = queryset.filter(
        pk=invitation_id, email=email, status=PENDING
    ).first()
    if invitation is None:
        raise emails.link_invalid()
    if invitation.expires_at <= timezone.now():
        raise emails.LinkExpired("token", emails.LinkExpired.detail, code=emails.LinkExpired.code)
    return invitation


def details(token: str) -> JoinDetails:
    invitation_id, tenant_id, email = read_token(token)
    with tenant_context(tenant_id):
        invitation = _open_invitation(invitation_id, email, lock=False)
        tenant = Tenant.objects.filter(pk=tenant_id, status=TenantStatus.ACTIVE).first()
        if tenant is None:
            raise emails.link_invalid()
        inviter = User.objects.get(pk=invitation.invited_by_id)
        return JoinDetails(
            email=str(invitation.email),
            legal_name=tenant.legal_name,
            role=invitation.role,
            invited_by_name=inviter.full_name,
            expires_at=invitation.expires_at,
        )


def join(token: str, *, full_name: str, password: str, client: ClientInfo) -> SessionTokens:
    """Create the account from the invitation, join the company, sign in."""
    invitation_id, tenant_id, email = read_token(token)
    _check_new_password(password, email=email, full_name=full_name)
    try:
        with transaction.atomic():
            if User.objects.filter(email=email).exists():
                raise Conflict(
                    "You already have an account: sign in, and accept the invitation there.",
                    code="account_exists",
                )
            user = User.objects.create(
                email=email,
                password_hash=make_password(password),
                full_name=full_name,
                email_verified_at=timezone.now(),  # the link proves the inbox
            )
            with tenant_context(tenant_id, user.pk):
                invitation = _open_invitation(invitation_id, email, lock=True)
                tenant = Tenant.objects.filter(pk=tenant_id, status=TenantStatus.ACTIVE).first()
                if tenant is None:
                    raise emails.link_invalid()
                Membership.objects.create(
                    tenant_id=tenant_id,
                    user=user,
                    role=invitation.role,
                    party_id=invitation.party_id,
                    status=MembershipStatus.ACTIVE,
                    invited_by_id=invitation.invited_by_id,
                )
                EmailInvitation.objects.filter(pk=invitation.pk).update(
                    status=EmailInvitationStatus.ACCEPTED,
                    accepted_by=user.pk,
                    updated_at=timezone.now(),
                )
                joined = str(user.pk)
                transaction.on_commit(lambda: notify.member_joined.delay(str(tenant_id), joined))
            tokens = _start_session(
                user_id=user.pk,
                tenant_id=tenant_id,
                role=invitation.role,
                # The link proved the inbox: as good as the emailed sign-in code.
                amr=frozenset({"pwd", "email"} if invitation.party_id else {"pwd"}),
                client=client,
                party_id=invitation.party_id,
            )
    except IntegrityError as exc:  # the address was taken a moment ago
        raise Conflict(
            "You already have an account: sign in, and accept the invitation there.",
            code="account_exists",
        ) from exc
    security_log.info("joined_by_email user=%s tenant=%s", user.pk, tenant_id)
    return _with_tenants(tokens, [TenantSummary(tenant_id, tenant.legal_name, invitation.role)])


def claim_for_new_user(user_id: uuid.UUID) -> int:
    """Signed up the normal way: pending email invitations become INVITED
    memberships, shown in the invitations banner."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT claim_email_invitations(%s)", [user_id])
        row = cursor.fetchone()
    claimed = int(row[0]) if row else 0
    if claimed:
        security_log.info("email_invitations_claimed user=%s count=%s", user_id, claimed)
    return claimed
