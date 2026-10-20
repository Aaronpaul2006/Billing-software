"""Account emails: address verification, password reset, password changed.

Links carry signed, expiring tokens (django.core.signing) rather than rows in
a table. A verification token names the address it confirms. A reset token
carries a keyed fingerprint of the current password hash, so it stops working
once the password changes: each reset link works once.

Tokens are made by the worker while it builds the email, so they never sit in
the task queue.
"""

import hmac
import uuid
from enum import StrEnum
from urllib.parse import urlencode

from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.crypto import salted_hmac

from apps.core.errors import Invalid

from .models import User, UserStatus

VERIFY_SALT = "accounts.verify-email"
RESET_SALT = "accounts.password-reset"


class Kind(StrEnum):
    VERIFY_EMAIL = "verify_email"
    PASSWORD_RESET = "password_reset"  # noqa: S105  # a template name
    PASSWORD_CHANGED = "password_changed"  # noqa: S105


class LinkInvalid(Invalid):
    code = "link_invalid"
    detail = "This link is not valid. It may have been used already."


class LinkExpired(Invalid):
    code = "link_expired"
    detail = "This link has expired. Ask for a new one."


def password_fingerprint(password_hash: str) -> str:
    return salted_hmac(RESET_SALT, password_hash).hexdigest()[:32]


def make_verify_token(user: User) -> str:
    return signing.dumps({"u": str(user.pk), "e": user.email}, salt=VERIFY_SALT)


def make_reset_token(user: User) -> str:
    return signing.dumps(
        {"u": str(user.pk), "p": password_fingerprint(user.password_hash)}, salt=RESET_SALT
    )


def link_invalid() -> LinkInvalid:
    return LinkInvalid("token", LinkInvalid.detail, code=LinkInvalid.code)


def _load(token: str, salt: str, max_age: int, field: str) -> tuple[uuid.UUID, str]:
    """(user id, payload[field]). Raises LinkInvalid / LinkExpired."""
    try:
        data = signing.loads(token, salt=salt, max_age=max_age)
    except signing.SignatureExpired as exc:
        raise LinkExpired("token", LinkExpired.detail, code=LinkExpired.code) from exc
    except signing.BadSignature as exc:
        raise link_invalid() from exc
    try:
        return uuid.UUID(data["u"]), str(data[field])
    except (TypeError, KeyError, ValueError) as exc:  # signed by us, but not this shape
        raise link_invalid() from exc


def read_verify_token(token: str) -> tuple[uuid.UUID, str]:
    """(user id, email the link confirms)."""
    return _load(token, VERIFY_SALT, settings.VERIFY_EMAIL_MAX_AGE, "e")


def read_reset_token(token: str) -> tuple[uuid.UUID, str]:
    """(user id, password fingerprint)."""
    return _load(token, RESET_SALT, settings.PASSWORD_RESET_MAX_AGE, "p")


def fingerprint_matches(user: User, fingerprint: str) -> bool:
    return hmac.compare_digest(fingerprint, password_fingerprint(user.password_hash))


def _link(page: str, token: str | None = None) -> str:
    url = f"{settings.APP_BASE_URL.rstrip('/')}/{page}"
    return f"{url}?{urlencode({'token': token})}" if token else url


def send(kind: Kind, user_id: uuid.UUID) -> bool:
    """Build and send one email. False when there is nothing to send."""
    user = User.objects.filter(pk=user_id, status=UserStatus.ACTIVE).first()
    if user is None:
        return False
    context: dict[str, object] = {"name": user.full_name}
    if kind is Kind.VERIFY_EMAIL:
        if user.email_verified_at is not None:
            return False
        subject = "Confirm your email address"
        context["link"] = _link("verify-email", make_verify_token(user))
        context["days"] = settings.VERIFY_EMAIL_MAX_AGE // 86400
    elif kind is Kind.PASSWORD_RESET:
        subject = "Reset your password"
        context["link"] = _link("reset-password", make_reset_token(user))
        context["minutes"] = settings.PASSWORD_RESET_MAX_AGE // 60
    else:
        subject = "Your password was changed"
        context["link"] = _link("forgot-password")
    body = render_to_string(f"accounts/email/{kind.value}.txt", context)
    send_mail(subject, body, None, [user.email])
    return True
