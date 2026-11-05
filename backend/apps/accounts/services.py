"""Authentication use cases: signup, login (+MFA), refresh rotation, sessions.

Plain functions (docs/01-architecture.md §4). Each manages its own
transactions explicitly, because some outcomes must be committed even when
the request then fails: a failed-login counter, or revoking a token family
after refresh-token reuse.
"""

import hashlib
import hmac
import logging
import secrets
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

import pyotp
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import F, Func, Max, Min, OuterRef, Q, Subquery, Value
from django.utils import timezone
from django.utils.crypto import salted_hmac

from apps.core.errors import Conflict, Forbidden, Invalid, NotFound, Unauthenticated
from apps.core.tenancy import Principal, tenant_context, user_context
from apps.tenants.models import Tenant, TenantStatus

from . import emails
from .crypto import decrypt_secret, encrypt_secret
from .emails import Kind
from .models import AuthSession, Membership, MembershipStatus, Role, User, UserStatus
from .tokens import (
    EMAIL,
    TOTP,
    InvalidToken,
    hash_refresh_token,
    issue_access_token,
    issue_mfa_challenge,
    new_refresh_token,
    verify_mfa_challenge,
)

security_log = logging.getLogger("security")

MFA_ROLES = frozenset({Role.OWNER, Role.ADMIN})
RECOVERY_CODE_COUNT = 10


# --- results & errors ------------------------------------------------------------


@dataclass(frozen=True)
class ClientInfo:
    ip: str | None = None
    user_agent: str | None = None
    device_label: str | None = None


@dataclass(frozen=True)
class TenantSummary:
    id: uuid.UUID
    legal_name: str
    role: str


@dataclass(frozen=True)
class SessionTokens:
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    session_id: uuid.UUID
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str
    amr: frozenset[str]
    tenants: list[TenantSummary] = field(default_factory=list)


@dataclass(frozen=True)
class MfaChallenge:
    mfa_token: str
    method: str = TOTP  # "totp": authenticator app; "email": a code we just emailed


class InvalidCredentials(Unauthenticated):
    code = "invalid_credentials"
    detail = "Invalid email or password."  # same for unknown email, bad password, locked


class InvalidRefreshToken(Unauthenticated):
    code = "invalid_refresh_token"
    detail = "The refresh token is invalid or expired. Sign in again."


class InvalidMfaCode(Unauthenticated):
    code = "invalid_mfa_code"
    detail = "The verification code is invalid."


# --- helpers ---------------------------------------------------------------------


def normalise_email(email: str) -> str:
    return email.strip().lower()


_dummy_hash: str | None = None


def _burn_password_check(password: str) -> None:
    """Spend the same time as a real check, so timing reveals no accounts."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = make_password(secrets.token_urlsafe(16))
    check_password(password, _dummy_hash)


def _is_locked(user: User) -> bool:
    return user.locked_until is not None and user.locked_until > timezone.now()


def _register_failure(user_id: uuid.UUID) -> None:
    """Count a failed password/MFA attempt; lock progressively (committed)."""
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        user.failed_login_count += 1
        over = user.failed_login_count - settings.LOGIN_LOCKOUT_THRESHOLD
        fields = ["failed_login_count", "updated_at"]
        if over >= 0:
            lock_for = min(timedelta(minutes=2 ** min(over, 10)), settings.LOGIN_LOCKOUT_MAX)
            user.locked_until = timezone.now() + lock_for
            fields.append("locked_until")
            security_log.warning("account_locked user=%s for=%s", user.pk, lock_for)
        user.save(update_fields=fields)
    security_log.info("login_failed user=%s", user_id)


def _reset_failures(user: User) -> None:
    if user.failed_login_count or user.locked_until:
        User.objects.filter(pk=user.pk).update(
            failed_login_count=0, locked_until=None, updated_at=timezone.now()
        )


def _start_session(
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    role: str,
    amr: frozenset[str],
    client: ClientInfo,
    family_id: uuid.UUID | None = None,
    party_id: uuid.UUID | None = None,
) -> SessionTokens:
    refresh_token, digest = new_refresh_token()
    family_id = family_id or uuid.uuid7()
    refresh_expires_at = timezone.now() + settings.REFRESH_TOKEN_TTL
    AuthSession.objects.create(
        user_id=user_id,
        tenant_id=tenant_id,
        family_id=family_id,
        refresh_token_hash=digest,
        device_label=client.device_label,
        ip=client.ip,
        user_agent=(client.user_agent or "")[:500] or None,
        expires_at=refresh_expires_at,
        amr=sorted(amr),
    )
    access_token, access_expires_at = issue_access_token(
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        session_id=family_id,
        amr=amr,
        party_id=party_id,
    )
    return SessionTokens(
        access_token=access_token,
        access_expires_at=access_expires_at,
        refresh_token=refresh_token,
        refresh_expires_at=refresh_expires_at,
        session_id=family_id,
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        amr=amr,
    )


def active_memberships(user_id: uuid.UUID) -> list[tuple[Membership, Tenant]]:
    """The user's active memberships in active tenants. Needs user_context."""
    memberships = list(
        Membership.objects.filter(user_id=user_id, status=MembershipStatus.ACTIVE).order_by(
            "created_at"
        )
    )
    tenants = {
        t.id: t
        for t in Tenant.objects.filter(
            id__in=[m.tenant_id for m in memberships], status=TenantStatus.ACTIVE
        )
    }
    return [(m, tenants[m.tenant_id]) for m in memberships if m.tenant_id in tenants]


def _check_new_password(
    password: str, *, email: str, full_name: str, field: str = "password"
) -> None:
    try:
        # The validators only read attributes (email, full_name) of `user`.
        validate_password(password, user=User(email=email, full_name=full_name))  # type: ignore[arg-type]
    except DjangoValidationError as exc:
        raise Invalid(field, " ".join(exc.messages), code="weak_password") from exc


def _email_after_commit(
    kind: Kind, user_id: uuid.UUID, extra: dict[str, str] | None = None
) -> None:
    """Queue an account email once the transaction commits. A broker outage is
    logged, not raised: the account change stands and the email can be resent."""
    from .tasks import send_account_email

    transaction.on_commit(
        lambda: send_account_email.delay(kind.value, str(user_id), extra), robust=True
    )


def revoke_family(family_id: uuid.UUID) -> int:
    return AuthSession.objects.filter(family_id=family_id, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )


def _revoke_all_sessions(user_id: uuid.UUID, *, except_family: uuid.UUID | None = None) -> None:
    sessions = AuthSession.objects.filter(user_id=user_id, revoked_at__isnull=True)
    if except_family is not None:
        sessions = sessions.exclude(family_id=except_family)
    sessions.update(revoked_at=timezone.now())


def session_is_live(family_id: uuid.UUID) -> bool:
    """True while the session family has an unrotated, unrevoked, unexpired token.

    Checked on every request, so logout and "revoke session" take effect
    immediately instead of when the 10-minute access token expires.
    """
    return AuthSession.objects.filter(
        family_id=family_id,
        revoked_at__isnull=True,
        rotated_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).exists()


# --- signup & login ----------------------------------------------------------------


def signup(
    *, email: str, password: str, full_name: str, business_name: str, client: ClientInfo
) -> SessionTokens:
    """Create a user, their first tenant and the OWNER membership."""
    email = normalise_email(email)
    _check_new_password(password, email=email, full_name=full_name)

    tenant_id = uuid.uuid7()
    try:
        with transaction.atomic():
            user = User.objects.create(
                email=email, password_hash=make_password(password), full_name=full_name
            )
            # db/schema.sql §8: choose the tenant id, make it the context, then
            # insert the tenant and its OWNER membership in one transaction.
            with tenant_context(tenant_id, user.id):
                Tenant.objects.create(id=tenant_id, legal_name=business_name)
                Membership.objects.create(tenant_id=tenant_id, user=user, role=Role.OWNER)
            tokens = _start_session(
                user_id=user.id,
                tenant_id=tenant_id,
                role=Role.OWNER,
                amr=frozenset({"pwd"}),
                client=client,
            )
            _email_after_commit(Kind.VERIFY_EMAIL, user.id)
            # Invited by email before signing up: those invitations wait in the banner.
            from .email_invitations import claim_for_new_user

            claim_for_new_user(user.id)
    except IntegrityError as exc:
        if User.objects.filter(email=email).exists():
            raise Invalid(
                "email", "An account with this email already exists.", code="email_taken"
            ) from exc
        raise
    security_log.info("signup user=%s tenant=%s", user.id, tenant_id)
    return _with_tenants(tokens, [TenantSummary(tenant_id, business_name, Role.OWNER)])


# --- email verification & password reset ------------------------------------------


def verify_email(token: str) -> None:
    """Confirm the address named in a verification link. Needs no sign-in:
    the link may be opened on another device."""
    user_id, email = emails.read_verify_token(token)
    updated = User.objects.filter(
        pk=user_id, email=email, status=UserStatus.ACTIVE, email_verified_at__isnull=True
    ).update(email_verified_at=timezone.now(), updated_at=timezone.now())
    if updated:
        security_log.info("email_verified user=%s", user_id)
    elif not User.objects.filter(pk=user_id, email=email, status=UserStatus.ACTIVE).exists():
        raise emails.link_invalid()
    # Already confirmed: opening the link again is fine.


def resend_verification(principal: Principal) -> None:
    user = User.objects.get(pk=principal.user_id)
    if user.email_verified_at is None:
        _email_after_commit(Kind.VERIFY_EMAIL, user.pk)


def require_verified_email(user_id: uuid.UUID) -> None:
    if not User.objects.filter(pk=user_id, email_verified_at__isnull=False).exists():
        raise Forbidden(
            "Confirm your email address before issuing documents.", code="email_not_verified"
        )


def forgot_password(email: str) -> None:
    """Email a reset link if an active account has this address. The response
    is the same either way, so it reveals nothing about which emails exist."""
    user = User.objects.filter(email=normalise_email(email), status=UserStatus.ACTIVE).first()
    if user is None:
        security_log.info("password_reset_requested unknown_email")
        return
    _email_after_commit(Kind.PASSWORD_RESET, user.pk)
    security_log.info("password_reset_requested user=%s", user.pk)


def reset_password(token: str, password: str) -> None:
    """Set a new password from a reset link, then sign out every session.

    Also clears a failed-login lock, and confirms the email address: the link
    could only have been read from that inbox.
    """
    user_id, fingerprint = emails.read_reset_token(token)
    with transaction.atomic():
        user = User.objects.select_for_update().filter(pk=user_id).first()
        if (
            user is None
            or user.status != UserStatus.ACTIVE
            or not emails.fingerprint_matches(user, fingerprint)
        ):
            raise emails.link_invalid()
        _check_new_password(password, email=user.email, full_name=user.full_name)
        now = timezone.now()
        user.password_hash = make_password(password)
        user.failed_login_count = 0
        user.locked_until = None
        user.email_verified_at = user.email_verified_at or now
        user.save(
            update_fields=[
                "password_hash",
                "failed_login_count",
                "locked_until",
                "email_verified_at",
                "updated_at",
            ]
        )
        _revoke_all_sessions(user.pk)
        _email_after_commit(Kind.PASSWORD_CHANGED, user.pk)
    security_log.warning("password_reset user=%s", user.pk)


# --- your account -------------------------------------------------------------------------


def update_profile(principal: Principal, changes: dict[str, Any]) -> User:
    """Name and phone; the email has its own confirmed flow."""
    if changes:
        User.objects.filter(pk=principal.user_id).update(**changes, updated_at=timezone.now())
    return User.objects.get(pk=principal.user_id)


def _check_current_password(user: User, password: str, field: str = "current_password") -> None:
    if not check_password(password, user.password_hash):
        _register_failure(user.pk)  # counts towards the lockout, like a failed login
        raise Invalid(field, "The password is incorrect.", code="invalid_password")


def change_password(principal: Principal, current: str, new: str) -> None:
    """Signs out every other device and sends a notice to the account's email."""
    user = User.objects.get(pk=principal.user_id)
    _check_current_password(user, current)
    _check_new_password(new, email=user.email, full_name=user.full_name, field="new_password")
    with transaction.atomic():
        User.objects.filter(pk=user.pk).update(
            password_hash=make_password(new),
            failed_login_count=0,
            locked_until=None,
            updated_at=timezone.now(),
        )
        _revoke_all_sessions(user.pk, except_family=principal.session_id)
        _email_after_commit(Kind.PASSWORD_CHANGED, user.pk)
    security_log.warning("password_changed user=%s", user.pk)


def request_email_change(principal: Principal, new_email: str, password: str) -> None:
    """Email a confirmation link to the new address; nothing changes until it
    is opened (so a typo cannot lock anyone out of their account)."""
    user = User.objects.get(pk=principal.user_id)
    _check_current_password(user, password, field="password")
    new_email = normalise_email(new_email)
    if new_email == user.email:
        raise Invalid("new_email", "That is already your email.", code="same_email")
    if User.objects.filter(email=new_email).exists():
        raise Invalid("new_email", "An account with this email already exists.", code="email_taken")
    _email_after_commit(Kind.CONFIRM_EMAIL_CHANGE, user.pk, {"new_email": new_email})
    security_log.info("email_change_requested user=%s", user.pk)


def confirm_email_change(token: str) -> None:
    """Switch to the new address (now verified) and tell the old one."""
    user_id, old, new = emails.read_email_change_token(token)
    user = User.objects.filter(pk=user_id, status=UserStatus.ACTIVE).first()
    if user is None:
        raise emails.link_invalid()
    if user.email == new:
        return  # opened twice: already done
    if user.email != old:
        raise emails.link_invalid()  # the email changed again in between
    try:
        with transaction.atomic():
            User.objects.filter(pk=user.pk, email=old).update(
                email=new, email_verified_at=timezone.now(), updated_at=timezone.now()
            )
            _email_after_commit(Kind.EMAIL_CHANGED, user.pk, {"old_email": old, "new_email": new})
    except IntegrityError as exc:
        raise Invalid(
            "token", "An account with this email already exists.", code="email_taken"
        ) from exc
    security_log.warning("email_changed user=%s", user.pk)


def login(
    *, email: str, password: str, tenant_id: uuid.UUID | None, client: ClientInfo
) -> SessionTokens | MfaChallenge:
    user = User.objects.filter(email=normalise_email(email)).first()
    if user is None or user.status != UserStatus.ACTIVE or _is_locked(user):
        _burn_password_check(password)
        if user is not None:
            security_log.info("login_rejected user=%s status=%s", user.pk, user.status)
        raise InvalidCredentials

    def upgrade_hash(raw: str) -> None:
        User.objects.filter(pk=user.pk).update(password_hash=make_password(raw))

    if not check_password(password, user.password_hash, setter=upgrade_hash):
        _register_failure(user.pk)
        raise InvalidCredentials
    _reset_failures(user)

    if user.mfa_enabled:
        return MfaChallenge(mfa_token=issue_mfa_challenge(user.pk))
    if _is_portal_user(user.pk):
        _send_email_code(user)
        return MfaChallenge(mfa_token=issue_mfa_challenge(user.pk, EMAIL), method=EMAIL)
    return _complete_login(user, frozenset({"pwd"}), tenant_id, client)


# --- sign-in codes by email (client-portal users without TOTP) -------------------


def _is_portal_user(user_id: uuid.UUID) -> bool:
    """Has an active CLIENT membership: signs in with password + emailed code."""
    with user_context(user_id):
        return any(m.role == Role.CLIENT for m, _ in active_memberships(user_id))


def _email_code_hash(user_id: uuid.UUID, code: str) -> str:
    return salted_hmac("accounts.email-code", f"{user_id}:{code}").hexdigest()


def _send_email_code(user: User) -> None:
    """A fresh 6-digit code (10 minutes, 5 tries); any earlier one stops working."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    with transaction.atomic():
        User.objects.filter(pk=user.pk).update(
            email_code_hash=_email_code_hash(user.pk, code),
            email_code_expires_at=timezone.now() + settings.EMAIL_CODE_TTL,
            email_code_attempts=0,
        )
        _email_after_commit(Kind.SIGN_IN_CODE, user.pk, {"code": code})
    security_log.info("email_code_sent user=%s", user.pk)


def _consume_email_code(user_id: uuid.UUID, code: str | None) -> bool:
    """Check the emailed code and use it up. A wrong code counts against its
    5 tries (committed even though sign-in then fails); the 5th wrong one, or
    an expired code, needs a new sign-in."""
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        live = (
            user.email_code_hash is not None
            and user.email_code_expires_at is not None
            and user.email_code_expires_at > timezone.now()
            and user.email_code_attempts < settings.EMAIL_CODE_MAX_ATTEMPTS
        )
        ok = (
            live
            and code is not None
            and hmac.compare_digest(user.email_code_hash or "", _email_code_hash(user.pk, code))
        )
        if ok or not live:
            User.objects.filter(pk=user.pk).update(
                email_code_hash=None, email_code_expires_at=None, email_code_attempts=0
            )
        else:
            User.objects.filter(pk=user.pk).update(email_code_attempts=F("email_code_attempts") + 1)
    return bool(ok)


def verify_mfa_login(
    *,
    mfa_token: str,
    code: str | None,
    recovery_code: str | None,
    tenant_id: uuid.UUID | None,
    client: ClientInfo,
) -> SessionTokens:
    try:
        user_id, method = verify_mfa_challenge(mfa_token)
    except InvalidToken as exc:
        raise Unauthenticated(
            "The sign-in attempt expired. Sign in again.", code="invalid_mfa_token"
        ) from exc
    user = User.objects.filter(pk=user_id, status=UserStatus.ACTIVE).first()
    if method == EMAIL:
        if user is None or _is_locked(user) or not _consume_email_code(user.pk, code):
            if user is not None:
                _register_failure(user.pk)
            raise InvalidMfaCode
        _reset_failures(user)
        return _complete_login(user, frozenset({"pwd", "email"}), tenant_id, client)
    if user is None or not user.mfa_enabled or _is_locked(user):
        raise InvalidMfaCode
    if not _consume_second_factor(user, code=code, recovery_code=recovery_code):
        _register_failure(user.pk)
        raise InvalidMfaCode
    _reset_failures(user)
    return _complete_login(user, frozenset({"pwd", "otp"}), tenant_id, client)


def _complete_login(
    user: User, amr: frozenset[str], tenant_id: uuid.UUID | None, client: ClientInfo
) -> SessionTokens:
    with user_context(user.pk):
        available = active_memberships(user.pk)
        if tenant_id is not None:
            chosen = next((mt for mt in available if mt[0].tenant_id == tenant_id), None)
            if chosen is None:
                raise NotFound
        elif available:
            chosen = available[0]
        else:
            raise Forbidden(
                "This account is not an active member of any business.",
                code="no_active_membership",
            )
        membership, _ = chosen
        tokens = _start_session(
            user_id=user.pk,
            tenant_id=membership.tenant_id,
            role=membership.role,
            amr=amr,
            client=client,
            party_id=membership.party_id,
        )
        User.objects.filter(pk=user.pk).update(last_login_at=timezone.now())
    security_log.info("login_succeeded user=%s amr=%s", user.pk, ",".join(sorted(amr)))
    return _with_tenants(tokens, [TenantSummary(t.id, t.legal_name, m.role) for m, t in available])


def _with_tenants(tokens: SessionTokens, tenants: list[TenantSummary]) -> SessionTokens:
    return replace(tokens, tenants=tenants)


# --- refresh, switch, logout -----------------------------------------------------


class RefreshTokenReused(InvalidRefreshToken):
    code = "refresh_token_reused"
    detail = "This sign-in was ended for security reasons. Sign in again."


def _refreshed_amr(session: AuthSession, user: User) -> frozenset[str]:
    """How the user signed in, kept across refreshes ("otp" only while TOTP
    is still on). Sessions from before amr was stored: derived as before."""
    if not session.amr:
        return frozenset({"pwd", "otp"} if user.mfa_enabled else {"pwd"})
    amr = frozenset(session.amr)
    return amr if user.mfa_enabled else amr - {"otp"}


def refresh(token: str, client: ClientInfo) -> SessionTokens:
    """Rotate a refresh token: the presented one is used up, a new one issued.

    Presenting an already-rotated token means it was copied (or replayed):
    the whole family is revoked. The row lock makes two concurrent refreshes
    with the same token behave the same way: one wins, the other is reuse.
    """
    outcome: SessionTokens | type[InvalidRefreshToken] = InvalidRefreshToken
    now = timezone.now()
    with transaction.atomic():
        session = (
            AuthSession.objects.select_for_update()
            .filter(refresh_token_hash=hash_refresh_token(token))
            .first()
        )
        if session is None or session.revoked_at is not None or session.expires_at <= now:
            pass
        elif session.rotated_at is not None:
            revoke_family(session.family_id)  # committed before we raise below
            security_log.warning(
                "refresh_token_reuse user=%s family=%s", session.user_id, session.family_id
            )
            outcome = RefreshTokenReused
        else:
            user = User.objects.get(pk=session.user_id)
            membership = None
            if user.status == UserStatus.ACTIVE and session.tenant_id is not None:
                with user_context(user.pk):
                    membership = next(
                        (
                            m
                            for m, _ in active_memberships(user.pk)
                            if m.tenant_id == session.tenant_id
                        ),
                        None,
                    )
            if membership is None:
                revoke_family(session.family_id)  # membership revoked: end the session
            else:
                session.rotated_at = now
                session.save(update_fields=["rotated_at"])
                outcome = _start_session(
                    user_id=user.pk,
                    tenant_id=membership.tenant_id,
                    role=membership.role,  # role re-checked at every refresh
                    amr=_refreshed_amr(session, user),
                    client=ClientInfo(client.ip, client.user_agent, session.device_label),
                    family_id=session.family_id,
                    party_id=membership.party_id,
                )
    if isinstance(outcome, SessionTokens):
        return outcome
    raise outcome


def switch_tenant(principal: Principal, tenant_id: uuid.UUID, client: ClientInfo) -> SessionTokens:
    with user_context(principal.user_id):
        available = active_memberships(principal.user_id)
        chosen = next((mt for mt in available if mt[0].tenant_id == tenant_id), None)
        if chosen is None:
            raise NotFound
        membership, _ = chosen
        if principal.session_id is not None:
            revoke_family(principal.session_id)
        tokens = _start_session(
            user_id=principal.user_id,
            tenant_id=tenant_id,
            role=membership.role,
            amr=principal.amr,
            client=client,
            party_id=membership.party_id,
        )
    return _with_tenants(tokens, [TenantSummary(t.id, t.legal_name, m.role) for m, t in available])


def logout(principal: Principal) -> None:
    if principal.session_id is not None:
        revoke_family(principal.session_id)


def logout_refresh_token(token: str) -> None:
    """Logout for a client that only holds the refresh token (web cookie)."""
    session = AuthSession.objects.filter(refresh_token_hash=hash_refresh_token(token)).first()
    if session is not None:
        revoke_family(session.family_id)


@dataclass(frozen=True)
class SessionInfo:
    id: uuid.UUID
    tenant_id: uuid.UUID | None
    device_label: str | None
    ip: str | None
    user_agent: str | None
    started_at: datetime
    last_refreshed_at: datetime
    current: bool


def list_sessions(principal: Principal) -> list[SessionInfo]:
    family = AuthSession.objects.filter(family_id=OuterRef("family_id"))
    live = (
        AuthSession.objects.filter(
            user_id=principal.user_id,
            revoked_at__isnull=True,
            rotated_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .annotate(
            started_at=Subquery(
                family.values("family_id").annotate(v=Min("created_at")).values("v")[:1]
            ),
            last_refreshed_at=Subquery(
                family.values("family_id").annotate(v=Max("created_at")).values("v")[:1]
            ),
        )
        .order_by("-created_at")
    )
    return [
        SessionInfo(
            id=s.family_id,
            tenant_id=s.tenant_id,
            device_label=s.device_label,
            ip=s.ip,
            user_agent=s.user_agent,
            started_at=s.started_at,
            last_refreshed_at=s.last_refreshed_at,
            current=s.family_id == principal.session_id,
        )
        for s in live
    ]


def revoke_session(principal: Principal, family_id: uuid.UUID) -> None:
    owned = AuthSession.objects.filter(user_id=principal.user_id, family_id=family_id)
    if not owned.exists():
        raise NotFound  # someone else's session: indistinguishable from none
    revoke_family(family_id)
    security_log.info("session_revoked user=%s family=%s", principal.user_id, family_id)


# --- MFA (TOTP) ----------------------------------------------------------------------


def _clock() -> float:
    return time.time()  # patched in tests to step through TOTP windows


def _match_totp(secret: str, code: str, last_step: int | None) -> int | None:
    """The time step `code` belongs to (±1 step for clock drift), if unused."""
    code = code.strip().replace(" ", "")
    if len(code) != 6 or not code.isdigit():
        return None
    totp = pyotp.TOTP(secret)
    now_step = int(_clock()) // totp.interval
    for step in (now_step - 1, now_step, now_step + 1):
        if hmac.compare_digest(totp.generate_otp(step), code) and (
            last_step is None or step > last_step
        ):
            return step
    return None


def _hash_recovery_code(code: str) -> str:
    normalised = code.strip().lower().replace("-", "").replace(" ", "")
    return hashlib.sha256(normalised.encode()).hexdigest()


def _consume_second_factor(user: User, *, code: str | None, recovery_code: str | None) -> bool:
    """Verify a TOTP or recovery code and use it up, atomically (no replay)."""
    if code:
        if user.mfa_secret_enc is None:
            return False
        secret = decrypt_secret(bytes(user.mfa_secret_enc), user_id=user.pk)
        step = _match_totp(secret, code, user.mfa_last_used_step)
        if step is None:
            return False
        claimed = User.objects.filter(
            Q(mfa_last_used_step__isnull=True) | Q(mfa_last_used_step__lt=step), pk=user.pk
        ).update(mfa_last_used_step=step)
        return claimed == 1
    if recovery_code:
        digest = _hash_recovery_code(recovery_code)
        used = User.objects.filter(pk=user.pk, mfa_recovery_codes__contains=[digest]).update(
            mfa_recovery_codes=Func(F("mfa_recovery_codes"), Value(digest), function="array_remove")
        )
        if used:
            security_log.info("mfa_recovery_code_used user=%s", user.pk)
        return used == 1
    return False


@dataclass(frozen=True)
class MfaSetup:
    secret: str
    otpauth_uri: str


def mfa_setup(principal: Principal) -> MfaSetup:
    user = User.objects.get(pk=principal.user_id)
    if user.mfa_enabled:
        raise Conflict("Two-factor authentication is already on.", code="mfa_already_enabled")
    secret = pyotp.random_base32()
    user.mfa_secret_enc = encrypt_secret(secret, user_id=user.pk)
    user.mfa_last_used_step = None
    user.save(update_fields=["mfa_secret_enc", "mfa_last_used_step", "updated_at"])
    uri = pyotp.TOTP(secret).provisioning_uri(
        name=str(user.email), issuer_name=settings.MFA_ISSUER_NAME
    )
    return MfaSetup(secret=secret, otpauth_uri=uri)


def mfa_enable(
    principal: Principal, code: str, client: ClientInfo
) -> tuple[list[str], SessionTokens]:
    """Turn MFA on after proving the authenticator works.

    Returns the one-time recovery codes (shown once, stored hashed) and new
    tokens with amr=[otp, pwd]. Every other session is signed out, so no
    session without MFA survives.
    """
    user = User.objects.get(pk=principal.user_id)
    if user.mfa_enabled:
        raise Conflict("Two-factor authentication is already on.", code="mfa_already_enabled")
    if user.mfa_secret_enc is None:
        raise Conflict("Start the setup first.", code="mfa_setup_required")
    if not _consume_second_factor(user, code=code, recovery_code=None):
        raise Invalid("code", "The verification code is invalid.", code="invalid_mfa_code")

    codes = [secrets.token_hex(5) for _ in range(RECOVERY_CODE_COUNT)]
    with transaction.atomic():
        User.objects.filter(pk=user.pk).update(
            mfa_enabled=True,
            mfa_recovery_codes=[_hash_recovery_code(c) for c in codes],
            updated_at=timezone.now(),
        )
        _revoke_all_sessions(user.pk)
        tokens = _start_session(
            user_id=user.pk,
            tenant_id=principal.tenant_id,
            role=principal.role,
            amr=frozenset({"pwd", "otp"}),
            client=client,
            party_id=principal.party_id,
        )
    security_log.info("mfa_enabled user=%s", user.pk)
    return [f"{c[:5]}-{c[5:]}" for c in codes], tokens


def mfa_new_recovery_codes(principal: Principal, password: str, code: str) -> list[str]:
    """Replace the recovery codes (Part B): the old ones stop working at once.

    Asks for the password and a current authenticator code (not a recovery
    code), like turning MFA off. Sessions stay as they are.
    """
    user = User.objects.get(pk=principal.user_id)
    if not user.mfa_enabled:
        raise Conflict("Two-factor authentication is not on.", code="mfa_not_enabled")
    if not check_password(password, user.password_hash):
        raise Invalid("password", "The password is incorrect.", code="invalid_password")
    if not _consume_second_factor(user, code=code, recovery_code=None):
        raise Invalid("code", "The verification code is invalid.", code="invalid_mfa_code")
    codes = [secrets.token_hex(5) for _ in range(RECOVERY_CODE_COUNT)]
    User.objects.filter(pk=user.pk).update(
        mfa_recovery_codes=[_hash_recovery_code(c) for c in codes], updated_at=timezone.now()
    )
    security_log.info("mfa_recovery_codes_replaced user=%s", user.pk)
    return [f"{c[:5]}-{c[5:]}" for c in codes]


def mfa_disable(principal: Principal, password: str, code: str) -> None:
    user = User.objects.get(pk=principal.user_id)
    if not user.mfa_enabled:
        raise Conflict("Two-factor authentication is not on.", code="mfa_not_enabled")
    with user_context(user.pk):
        privileged = any(m.role in MFA_ROLES for m, _ in active_memberships(user.pk))
    if privileged:
        raise Conflict(
            "Owners and admins must keep two-factor authentication on.",
            code="mfa_required_for_role",
        )
    if not check_password(password, user.password_hash):
        raise Invalid("password", "The password is incorrect.", code="invalid_password")
    if not _consume_second_factor(user, code=code, recovery_code=None):
        raise Invalid("code", "The verification code is invalid.", code="invalid_mfa_code")
    with transaction.atomic():
        User.objects.filter(pk=user.pk).update(
            mfa_enabled=False,
            mfa_secret_enc=None,
            mfa_recovery_codes=[],
            mfa_last_used_step=None,
            updated_at=timezone.now(),
        )
        _revoke_all_sessions(user.pk, except_family=principal.session_id)
    security_log.info("mfa_disabled user=%s", user.pk)
