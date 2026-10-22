"""Your account (K.1): profile, password change, email change with confirmation."""

import re
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.accounts.emails import make_email_change_token
from apps.accounts.models import User

from .conftest import PASSWORD, Account, Clock, bearer, enable_mfa

pytestmark = pytest.mark.django_db

MakeAccount = Callable[..., Account]
NEW_PASSWORD = "a different long passphrase"


@pytest.fixture
def api() -> APIClient:
    client = APIClient()
    client.default_format = "json"
    return client


@pytest.fixture
def owner(api: APIClient, make_account: MakeAccount, clock: Clock) -> tuple[Account, str, str]:
    """(account, access token with two-step done, TOTP secret)."""
    account = make_account()
    secret, enabled = enable_mfa(api, account, clock)
    return account, enabled["access_token"], secret


def _problem(response: Any) -> tuple[int, str]:
    body = response.json()
    code = body["errors"][0]["code"] if body["code"] == "validation_error" else body["code"]
    return response.status_code, code


def _second_device(api: APIClient, account: Account, secret: str, clock: Clock) -> str:
    clock.advance()
    challenge = api.post(
        "/api/v1/auth/login", {"email": account.email, "password": PASSWORD}
    ).json()["mfa_token"]
    verified = api.post(
        "/api/v1/auth/mfa/verify", {"mfa_token": challenge, "code": clock.code(secret)}
    )
    assert verified.status_code == 200, verified.content
    token: str = verified.json()["access_token"]
    return token


def test_profile(api: APIClient, owner: tuple[Account, str, str]) -> None:
    _, token, _ = owner
    response = api.patch(
        "/api/v1/me", {"full_name": "Priya N.", "phone": "+91 98470 12345"}, **bearer(token)
    )
    assert response.status_code == 200, response.content
    assert (response.json()["full_name"], response.json()["phone"]) == (
        "Priya N.",
        "+919847012345",  # stored without spaces (the database rule)
    )
    assert _problem(api.patch("/api/v1/me", {"phone": "call me"}, **bearer(token))) == (
        422,
        "invalid",
    )


def test_change_password_signs_out_the_other_devices(
    api: APIClient,
    owner: tuple[Account, str, str],
    clock: Clock,
    django_capture_on_commit_callbacks: Any,
) -> None:
    account, token, secret = owner
    other = _second_device(api, account, secret, clock)
    url = "/api/v1/auth/password/change"
    wrong = api.post(
        url, {"current_password": "wrong one", "new_password": NEW_PASSWORD}, **bearer(token)
    )
    assert _problem(wrong) == (422, "invalid_password")
    assert wrong.json()["errors"][0]["field"] == "current_password"
    weak = api.post(url, {"current_password": PASSWORD, "new_password": "short"}, **bearer(token))
    assert _problem(weak) == (422, "weak_password")
    assert weak.json()["errors"][0]["field"] == "new_password"
    with django_capture_on_commit_callbacks(execute=True):
        done = api.post(
            url, {"current_password": PASSWORD, "new_password": NEW_PASSWORD}, **bearer(token)
        )
    assert done.status_code == 204
    assert mail.outbox[-1].subject == "Your password was changed"
    assert api.get("/api/v1/me", **bearer(other)).status_code == 401  # signed out
    assert api.get("/api/v1/me", **bearer(token)).status_code == 200  # this device stays
    login = api.post("/api/v1/auth/login", {"email": account.email, "password": NEW_PASSWORD})
    assert login.status_code == 200


def test_change_email_only_after_the_new_address_confirms(
    api: APIClient,
    owner: tuple[Account, str, str],
    make_account: MakeAccount,
    settings: Any,
    django_capture_on_commit_callbacks: Any,
) -> None:
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, "email_change_user": (20, 3600)}
    account, token, _ = owner
    url = "/api/v1/me/email"

    def ask(new_email: str, password: str = PASSWORD) -> Any:
        return api.post(url, {"new_email": new_email, "password": password}, **bearer(token))

    wrong = ask("x@example.com", "nope")
    assert _problem(wrong) == (422, "invalid_password")
    assert wrong.json()["errors"][0]["field"] == "password"
    assert _problem(ask(account.email.upper())) == (422, "same_email")
    assert _problem(ask(make_account().email)) == (422, "email_taken")

    with django_capture_on_commit_callbacks(execute=True):
        assert ask("new.address@example.com").status_code == 204
    message = mail.outbox[-1]
    assert message.to == ["new.address@example.com"]
    link = re.search(r"https://app\.example\.test/confirm-email\?\S+", str(message.body))
    assert link, message.body
    link_token = parse_qs(urlparse(link.group(0)).query)["token"][0]
    assert User.objects.get(email=account.email)  # nothing changed yet

    with django_capture_on_commit_callbacks(execute=True):
        confirmed = api.post("/api/v1/auth/email/confirm", {"token": link_token})
    assert confirmed.status_code == 204
    me = api.get("/api/v1/me", **bearer(token)).json()
    assert (me["email"], me["email_verified"]) == ("new.address@example.com", True)
    notice = mail.outbox[-1]
    assert (notice.to, notice.subject) == ([account.email], "Your sign-in email was changed")
    # Opening the link again is harmless; a link made for the old address is not.
    assert api.post("/api/v1/auth/email/confirm", {"token": link_token}).status_code == 204
    user = User.objects.get(email="new.address@example.com")
    user.email = account.email  # as it was when that link was sent
    stale = make_email_change_token(user, "third@example.com")
    assert _problem(api.post("/api/v1/auth/email/confirm", {"token": stale})) == (
        422,
        "link_invalid",
    )
