"""Email verification and password reset (docs/02-api-design.md §2)."""

import re
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from django.core import mail, signing
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.emails import RESET_SALT, VERIFY_SALT
from apps.accounts.models import AuthSession, User

from .conftest import PASSWORD, Account, bearer

pytestmark = pytest.mark.django_db

MakeAccount = Callable[..., Account]
NEW_PASSWORD = "a brand new passphrase 42"


@pytest.fixture
def api() -> APIClient:
    client = APIClient()
    client.default_format = "json"  # the API accepts JSON only
    return client


@pytest.fixture
def send_now(django_capture_on_commit_callbacks: Any) -> Callable[[], Any]:
    """`with send_now():` runs the after-commit email hooks (Celery is eager in tests)."""
    return lambda: django_capture_on_commit_callbacks(execute=True)


def _token(message: mail.EmailMessage, page: str) -> str:
    match = re.search(rf"https://app\.example\.test/{page}\?\S+", str(message.body))
    assert match, message.body
    return parse_qs(urlparse(match.group(0)).query)["token"][0]


def _problem(response: Any) -> tuple[int, str]:
    body = response.json()
    code = body["errors"][0]["code"] if body["code"] == "validation_error" else body["code"]
    return response.status_code, code


def _signup(api: APIClient, make_account: MakeAccount, send_now: Any) -> Account:
    with send_now():
        account = make_account()
    return account


# --- verification --------------------------------------------------------------------


def test_signup_sends_a_verification_link_that_confirms_the_address(
    api: APIClient, make_account: MakeAccount, send_now: Any
) -> None:
    account = _signup(api, make_account, send_now)
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == [account.email]
    assert message.subject == "Confirm your email address"
    assert "Priya Nair" in str(message.body)

    me = api.get("/api/v1/me", **bearer(account.access)).json()
    assert me["email_verified"] is False

    token = _token(message, "verify-email")
    assert api.post("/api/v1/auth/verify-email", {"token": token}).status_code == 204
    assert api.get("/api/v1/me", **bearer(account.access)).json()["email_verified"] is True
    # Opening the link again is harmless.
    assert api.post("/api/v1/auth/verify-email", {"token": token}).status_code == 204


def test_verification_link_rejects_tampering_expiry_and_another_address(
    api: APIClient, make_account: MakeAccount, send_now: Any
) -> None:
    account = _signup(api, make_account, send_now)
    token = _token(mail.outbox[0], "verify-email")
    tampered = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    assert _problem(api.post("/api/v1/auth/verify-email", {"token": tampered})) == (
        422,
        "link_invalid",
    )
    user = User.objects.get(email=account.email)
    # A reset token is signed with another salt: it cannot verify an address.
    reset_like = signing.dumps({"u": str(user.pk), "e": user.email}, salt=RESET_SALT)
    assert _problem(api.post("/api/v1/auth/verify-email", {"token": reset_like}))[1] == (
        "link_invalid"
    )
    # The address changed since the link was sent.
    User.objects.filter(pk=user.pk).update(email="other@example.com")
    assert _problem(api.post("/api/v1/auth/verify-email", {"token": token}))[1] == "link_invalid"
    User.objects.filter(pk=user.pk).update(email=account.email)

    with override_settings(VERIFY_EMAIL_MAX_AGE=-1):
        assert _problem(api.post("/api/v1/auth/verify-email", {"token": token})) == (
            422,
            "link_expired",
        )
    assert User.objects.get(pk=user.pk).email_verified_at is None


def test_resend_sends_a_new_link_until_verified(
    api: APIClient, make_account: MakeAccount, send_now: Any
) -> None:
    account = _signup(api, make_account, send_now)
    with send_now():
        assert api.post(
            "/api/v1/auth/verify-email/resend", **bearer(account.access)
        ).status_code == (204)
    assert len(mail.outbox) == 2
    token = _token(mail.outbox[1], "verify-email")
    assert api.post("/api/v1/auth/verify-email", {"token": token}).status_code == 204
    with send_now():
        assert api.post(
            "/api/v1/auth/verify-email/resend", **bearer(account.access)
        ).status_code == (204)
    assert len(mail.outbox) == 2  # already verified: nothing sent
    assert api.post("/api/v1/auth/verify-email/resend").status_code == 401


def test_verify_token_is_not_a_signed_in_session(api: APIClient) -> None:
    forged = signing.dumps({"u": "not-a-user"}, salt=VERIFY_SALT)
    assert _problem(api.post("/api/v1/auth/verify-email", {"token": forged}))[0] == 422
    assert _problem(api.post("/api/v1/auth/verify-email", {"token": "garbage"})) == (
        422,
        "link_invalid",
    )


# --- password reset ------------------------------------------------------------------


def _reset_link(api: APIClient, email: str, send_now: Any) -> str:
    before = len(mail.outbox)
    with send_now():
        assert api.post("/api/v1/auth/password/forgot", {"email": email}).status_code == 204
    assert len(mail.outbox) == before + 1
    message = mail.outbox[-1]
    assert message.subject == "Reset your password"
    return _token(message, "reset-password")


def test_forgot_password_answers_the_same_for_unknown_emails(api: APIClient, send_now: Any) -> None:
    with send_now():
        response = api.post("/api/v1/auth/password/forgot", {"email": "nobody@example.com"})
    assert response.status_code == 204
    assert mail.outbox == []


def test_reset_sets_the_password_signs_out_everywhere_and_works_once(
    api: APIClient, make_account: MakeAccount, send_now: Any
) -> None:
    account = _signup(api, make_account, send_now)
    user = User.objects.get(email=account.email)
    User.objects.filter(pk=user.pk).update(failed_login_count=9)
    token = _reset_link(api, account.email.upper(), send_now)

    weak = api.post("/api/v1/auth/password/reset", {"token": token, "password": "short"})
    assert _problem(weak) == (422, "weak_password")

    with send_now():
        done = api.post("/api/v1/auth/password/reset", {"token": token, "password": NEW_PASSWORD})
    assert done.status_code == 204
    assert mail.outbox[-1].subject == "Your password was changed"

    user.refresh_from_db()
    assert user.failed_login_count == 0
    assert user.email_verified_at is not None  # the link proved the inbox
    assert not AuthSession.objects.filter(user=user, revoked_at__isnull=True).exists()
    assert api.get("/api/v1/me", **bearer(account.access)).status_code == 401

    again = api.post(
        "/api/v1/auth/password/reset", {"token": token, "password": "x" + NEW_PASSWORD}
    )
    assert _problem(again) == (422, "link_invalid")

    old = api.post("/api/v1/auth/login", {"email": account.email, "password": PASSWORD})
    assert old.status_code == 401
    new = api.post("/api/v1/auth/login", {"email": account.email, "password": NEW_PASSWORD})
    assert new.status_code == 200, new.content


def test_reset_link_expires(api: APIClient, make_account: MakeAccount, send_now: Any) -> None:
    account = _signup(api, make_account, send_now)
    token = _reset_link(api, account.email, send_now)
    with override_settings(PASSWORD_RESET_MAX_AGE=-1):
        response = api.post(
            "/api/v1/auth/password/reset", {"token": token, "password": NEW_PASSWORD}
        )
    assert _problem(response) == (422, "link_expired")


def test_a_verification_link_cannot_reset_a_password(
    api: APIClient, make_account: MakeAccount, send_now: Any
) -> None:
    _signup(api, make_account, send_now)
    token = _token(mail.outbox[0], "verify-email")
    response = api.post("/api/v1/auth/password/reset", {"token": token, "password": NEW_PASSWORD})
    assert _problem(response) == (422, "link_invalid")


def test_disabled_accounts_get_no_reset_email(
    api: APIClient, make_account: MakeAccount, send_now: Any
) -> None:
    account = _signup(api, make_account, send_now)
    token = _reset_link(api, account.email, send_now)
    User.objects.filter(email=account.email).update(status="DISABLED")
    with send_now():
        api.post("/api/v1/auth/password/forgot", {"email": account.email})
    assert len(mail.outbox) == 2  # the verification and the first reset only
    response = api.post("/api/v1/auth/password/reset", {"token": token, "password": NEW_PASSWORD})
    assert _problem(response) == (422, "link_invalid")
