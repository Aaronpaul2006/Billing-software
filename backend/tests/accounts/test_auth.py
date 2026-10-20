"""Authentication: signup, login, tokens, refresh rotation, sessions, MFA.

docs/01-architecture.md §6 and docs/02-api-design.md §2.
"""

import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import jwt
import pytest
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import AuthSession, Membership, MembershipStatus, Role, User
from apps.core.tenancy import tenant_context
from apps.tenants.models import Tenant

from .conftest import PASSWORD, Account, Clock, bearer, enable_mfa

pytestmark = pytest.mark.django_db

MakeAccount = Callable[..., Account]


def _login(api: APIClient, email: str, password: str = PASSWORD, **extra: Any) -> Any:
    return api.post(
        "/api/v1/auth/login", {"email": email, "password": password, **extra}, format="json"
    )


def _problem(response: Any) -> tuple[int, str]:
    return response.status_code, response.json()["code"]


# --- signup ------------------------------------------------------------------------


def test_signup_creates_user_tenant_and_owner_membership(make_account: MakeAccount) -> None:
    account = make_account("Nair Constructions")
    body = account.signup
    assert body["role"] == "OWNER"
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 600
    assert body["refresh_token"]
    assert body["mfa_enrollment_required"] is True
    assert body["tenants"] == [
        {"id": account.tenant_id, "legal_name": "Nair Constructions", "role": "OWNER"}
    ]

    user = User.objects.get(email=account.email)
    assert user.password_hash != PASSWORD
    assert "$" in user.password_hash
    with tenant_context(account.tenant_id, user.pk):
        assert Tenant.objects.get().legal_name == "Nair Constructions"
        assert Membership.objects.get(user=user).role == Role.OWNER


def test_signup_rejects_weak_password(api: APIClient) -> None:
    response = api.post(
        "/api/v1/auth/signup",
        {
            "email": "a@example.com",
            "password": "password123",
            "full_name": "A",
            "business_name": "B",
        },
        format="json",
    )
    assert _problem(response) == (422, "validation_error")
    assert response.json()["errors"][0]["field"] == "password"
    assert response.json()["errors"][0]["code"] == "weak_password"
    assert not User.objects.filter(email="a@example.com").exists()


def test_signup_rejects_duplicate_email_case_insensitively(
    api: APIClient, make_account: MakeAccount
) -> None:
    account = make_account()
    response = api.post(
        "/api/v1/auth/signup",
        {
            "email": account.email.upper(),
            "password": PASSWORD,
            "full_name": "X",
            "business_name": "Y",
        },
        format="json",
    )
    assert _problem(response) == (422, "validation_error")
    assert response.json()["errors"][0]["code"] == "email_taken"


# --- login ---------------------------------------------------------------------------


def test_login_returns_tokens(api: APIClient, make_account: MakeAccount) -> None:
    account = make_account()
    response = _login(api, account.email.upper())  # email is case-insensitive
    assert response.status_code == 200
    assert response.json()["tenant_id"] == account.tenant_id
    assert response["Cache-Control"] == "no-store"


def test_wrong_password_and_unknown_email_look_identical(
    api: APIClient, make_account: MakeAccount
) -> None:
    account = make_account()
    wrong = _login(api, account.email, "not the password at all")
    unknown = _login(api, "nobody-here@example.com", "not the password at all")
    for response in (wrong, unknown):
        assert response.status_code == 401
        assert response["WWW-Authenticate"].startswith("Bearer")

    def strip(response: Any) -> dict[str, Any]:
        return {k: v for k, v in response.json().items() if k != "request_id"}

    assert strip(wrong) == strip(unknown)
    assert wrong.json()["code"] == "invalid_credentials"


def test_repeated_failures_lock_the_account(
    api: APIClient, make_account: MakeAccount, settings: Any
) -> None:
    # The database lockout on its own, without the Redis per-email limit in front.
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, "login_email": (100, 60)}
    account = make_account()
    for _ in range(settings.LOGIN_LOCKOUT_THRESHOLD):
        assert _login(api, account.email, "wrong password!!").status_code == 401
    user = User.objects.get(email=account.email)
    assert user.locked_until is not None
    assert user.locked_until > timezone.now()
    # even the right password is refused while locked, with the same answer
    assert _problem(_login(api, account.email)) == (401, "invalid_credentials")

    User.objects.filter(pk=user.pk).update(locked_until=timezone.now() - timedelta(seconds=1))
    assert _login(api, account.email).status_code == 200
    assert User.objects.get(pk=user.pk).failed_login_count == 0


def test_public_endpoints_ignore_a_stale_bearer_token(
    api: APIClient, make_account: MakeAccount
) -> None:
    account = make_account()
    response = _login(api, account.email, HTTP_AUTHORIZATION="Bearer garbage")
    assert response.status_code == 200


# --- access tokens -------------------------------------------------------------------


def test_me_with_valid_token(api: APIClient, make_account: MakeAccount) -> None:
    account = make_account()
    response = api.get("/api/v1/me", **bearer(account.access))
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == account.email
    assert body["role"] == "OWNER"
    assert body["memberships"][0]["tenant_id"] == account.tenant_id


def test_missing_token_is_401_with_challenge(api: APIClient) -> None:
    response = api.get("/api/v1/me")
    assert _problem(response) == (401, "not_authenticated")
    assert response["WWW-Authenticate"] == 'Bearer realm="api"'


def _forge(claims: dict[str, Any], key: str | None = None, algorithm: str = "HS256") -> str:
    now = int(timezone.now().timestamp())
    payload = {
        "iss": settings.JWT_ISSUER,
        "iat": now,
        "exp": now + 600,
        "typ": "access",
        "sub": str(uuid.uuid4()),
        "tid": str(uuid.uuid4()),
        "role": "OWNER",
        "sid": str(uuid.uuid4()),
        "amr": ["otp", "pwd"],
        **claims,
    }
    return jwt.encode(payload, key or settings.JWT_SIGNING_KEY, algorithm=algorithm)


@pytest.mark.parametrize(
    ("token_factory", "code"),
    [
        (lambda a: "not-a-jwt", "invalid_token"),
        (lambda a: a.access[:-4] + "AAAA", "invalid_token"),  # tampered signature
        (lambda a: _forge({}, key="some-other-key-of-sufficient-length-123"), "invalid_token"),
        (lambda a: _forge({"typ": "mfa_challenge"}), "invalid_token"),
        (lambda a: _forge({"exp": int(timezone.now().timestamp()) - 120}), "token_expired"),
        (lambda a: _forge({"iss": "someone-else"}), "invalid_token"),
        # well-formed and signed, but no such session: forged sid
        (lambda a: _forge({}), "session_revoked"),
    ],
)
def test_bad_access_tokens_are_rejected(
    api: APIClient,
    make_account: MakeAccount,
    token_factory: Callable[[Account], str],
    code: str,
) -> None:
    token = token_factory(make_account())
    assert _problem(api.get("/api/v1/me", **bearer(token))) == (401, code)


def test_unsigned_alg_none_token_is_rejected(api: APIClient) -> None:
    header_payload = _forge({}).rsplit(".", 1)[0]
    none_token = jwt.encode({"sub": "x"}, None, algorithm="none")  # type: ignore[arg-type]
    for token in (none_token, header_payload + "."):
        assert _problem(api.get("/api/v1/me", **bearer(token))) == (401, "invalid_token")


# --- refresh rotation & sessions ------------------------------------------------------


def _refresh(api: APIClient, token: str) -> Any:
    return api.post("/api/v1/auth/token/refresh", {"refresh_token": token}, format="json")


def test_refresh_rotates_and_reuse_revokes_the_family(
    api: APIClient, make_account: MakeAccount
) -> None:
    account = make_account()
    first_refresh = account.signup["refresh_token"]

    rotated = _refresh(api, first_refresh)
    assert rotated.status_code == 200
    second_refresh = rotated.json()["refresh_token"]
    assert second_refresh != first_refresh
    assert rotated.json()["session_id"] == account.signup["session_id"]  # same family

    # the old token is presented again: theft is assumed, the family dies
    assert _problem(_refresh(api, first_refresh)) == (401, "refresh_token_reused")
    assert _problem(_refresh(api, second_refresh)) == (401, "invalid_refresh_token")
    access = rotated.json()["access_token"]
    assert _problem(api.get("/api/v1/me", **bearer(access))) == (401, "session_revoked")


def test_refresh_rejects_unknown_and_expired_tokens(
    api: APIClient, make_account: MakeAccount
) -> None:
    account = make_account()
    assert _problem(_refresh(api, "made-up-token")) == (401, "invalid_refresh_token")
    AuthSession.objects.filter(family_id=account.signup["session_id"]).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    assert _problem(_refresh(api, account.signup["refresh_token"])) == (
        401,
        "invalid_refresh_token",
    )


def test_refresh_rechecks_membership(api: APIClient, make_account: MakeAccount) -> None:
    account = make_account()
    user = User.objects.get(email=account.email)
    with tenant_context(account.tenant_id, user.pk):
        Membership.objects.filter(user=user).update(status=MembershipStatus.REVOKED)
    assert _problem(_refresh(api, account.signup["refresh_token"])) == (
        401,
        "invalid_refresh_token",
    )
    assert _problem(api.get("/api/v1/me", **bearer(account.access))) == (401, "session_revoked")


def test_logout_ends_the_session_immediately(api: APIClient, make_account: MakeAccount) -> None:
    account = make_account()
    assert api.post("/api/v1/auth/logout", **bearer(account.access)).status_code == 204
    assert _problem(api.get("/api/v1/me", **bearer(account.access))) == (401, "session_revoked")
    assert _refresh(api, account.signup["refresh_token"]).status_code == 401


def test_sessions_list_and_revoke(api: APIClient, make_account: MakeAccount) -> None:
    account = make_account()
    other_device = _login(api, account.email, device_label="Site tablet").json()

    listed = api.get("/api/v1/auth/sessions", **bearer(account.access)).json()["results"]
    assert {s["id"] for s in listed} == {account.signup["session_id"], other_device["session_id"]}
    assert [s["current"] for s in listed if s["id"] == account.signup["session_id"]] == [True]

    revoked = api.delete(
        f"/api/v1/auth/sessions/{other_device['session_id']}", **bearer(account.access)
    )
    assert revoked.status_code == 204
    assert _problem(api.get("/api/v1/me", **bearer(other_device["access_token"]))) == (
        401,
        "session_revoked",
    )


def test_cannot_revoke_someone_elses_session(api: APIClient, make_account: MakeAccount) -> None:
    mine, theirs = make_account(), make_account()
    response = api.delete(
        f"/api/v1/auth/sessions/{theirs.signup['session_id']}", **bearer(mine.access)
    )
    assert _problem(response) == (404, "not_found")
    assert api.get("/api/v1/me", **bearer(theirs.access)).status_code == 200


def test_web_client_gets_refresh_token_only_as_httponly_cookie(
    api: APIClient, make_account: MakeAccount
) -> None:
    account = make_account()
    response = _login(api, account.email, client="web")
    assert "refresh_token" not in response.json()
    cookie = response.cookies[settings.REFRESH_COOKIE_NAME]
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Strict"
    assert cookie["path"] == "/api/v1/auth"

    refreshed = api.post("/api/v1/auth/token/refresh", format="json")  # cookie only
    assert refreshed.status_code == 200
    assert "refresh_token" not in refreshed.json()
    assert refreshed.cookies[settings.REFRESH_COOKIE_NAME].value != cookie.value


# --- switching tenants -----------------------------------------------------------------


def test_switch_tenant_requires_membership(api: APIClient, make_account: MakeAccount) -> None:
    account = make_account("First Co")
    other = make_account("Second Co")
    user = User.objects.get(email=account.email)
    with tenant_context(other.tenant_id, user.pk):
        Membership.objects.create(tenant_id=other.tenant_id, user=user, role=Role.ACCOUNTANT)

    switched = api.post(
        "/api/v1/auth/switch-tenant",
        {"tenant_id": other.tenant_id},
        format="json",
        **bearer(account.access),
    )
    assert switched.status_code == 200
    assert switched.json()["tenant_id"] == other.tenant_id
    assert switched.json()["role"] == "ACCOUNTANT"
    # the previous session (tenant 1) is replaced
    assert api.get("/api/v1/me", **bearer(account.access)).status_code == 401

    stranger = make_account("Third Co")
    denied = api.post(
        "/api/v1/auth/switch-tenant",
        {"tenant_id": stranger.tenant_id},
        format="json",
        **bearer(switched.json()["access_token"]),
    )
    assert _problem(denied) == (404, "not_found")


# --- MFA -------------------------------------------------------------------------------


def test_owner_without_mfa_is_limited_to_enrolment(
    api: APIClient, make_account: MakeAccount
) -> None:
    account = make_account()
    assert api.get("/api/v1/me", **bearer(account.access)).status_code == 200
    blocked = api.post(
        "/api/v1/auth/mfa/disable",
        {"password": PASSWORD, "code": "000000"},
        format="json",
        **bearer(account.access),
    )
    assert _problem(blocked) == (403, "mfa_enrollment_required")


def test_enable_mfa_then_login_needs_a_code(
    api: APIClient, make_account: MakeAccount, clock: Clock
) -> None:
    account = make_account()
    secret, enabled = enable_mfa(api, account, clock)
    assert len(enabled["recovery_codes"]) == 10
    assert enabled["mfa_enrollment_required"] is False
    # every pre-MFA session was signed out
    assert _problem(api.get("/api/v1/me", **bearer(account.access))) == (401, "session_revoked")
    assert api.get("/api/v1/me", **bearer(enabled["access_token"])).status_code == 200

    challenge = _login(api, account.email).json()
    assert challenge["mfa_required"] is True
    assert "access_token" not in challenge

    clock.advance()
    verified = api.post(
        "/api/v1/auth/mfa/verify",
        {"mfa_token": challenge["mfa_token"], "code": clock.code(secret)},
        format="json",
    )
    assert verified.status_code == 200
    assert verified.json()["mfa_enrollment_required"] is False

    # the same code cannot be used twice
    replay = api.post(
        "/api/v1/auth/mfa/verify",
        {"mfa_token": challenge["mfa_token"], "code": clock.code(secret)},
        format="json",
    )
    assert _problem(replay) == (401, "invalid_mfa_code")


def test_wrong_mfa_code_and_bad_challenge(
    api: APIClient, make_account: MakeAccount, clock: Clock
) -> None:
    account = make_account()
    enable_mfa(api, account, clock)
    challenge = _login(api, account.email).json()["mfa_token"]
    wrong = api.post(
        "/api/v1/auth/mfa/verify", {"mfa_token": challenge, "code": "000000"}, format="json"
    )
    assert _problem(wrong) == (401, "invalid_mfa_code")
    forged = api.post(
        "/api/v1/auth/mfa/verify", {"mfa_token": "forged", "code": "123456"}, format="json"
    )
    assert _problem(forged) == (401, "invalid_mfa_token")


def test_recovery_code_works_once(api: APIClient, make_account: MakeAccount, clock: Clock) -> None:
    account = make_account()
    _, enabled = enable_mfa(api, account, clock)
    code = enabled["recovery_codes"][0]

    def verify() -> Any:
        challenge = _login(api, account.email).json()["mfa_token"]
        return api.post(
            "/api/v1/auth/mfa/verify",
            {"mfa_token": challenge, "recovery_code": code.upper()},
            format="json",
        )

    assert verify().status_code == 200
    assert _problem(verify()) == (401, "invalid_mfa_code")
    assert len(User.objects.get(email=account.email).mfa_recovery_codes) == 9


def test_mfa_secret_is_stored_encrypted(
    api: APIClient, make_account: MakeAccount, clock: Clock
) -> None:
    account = make_account()
    secret, _ = enable_mfa(api, account, clock)
    stored = bytes(User.objects.get(email=account.email).mfa_secret_enc or b"")
    assert stored
    assert secret.encode() not in stored


def test_owner_cannot_disable_mfa(api: APIClient, make_account: MakeAccount, clock: Clock) -> None:
    account = make_account()
    secret, enabled = enable_mfa(api, account, clock)
    clock.advance()
    response = api.post(
        "/api/v1/auth/mfa/disable",
        {"password": PASSWORD, "code": clock.code(secret)},
        format="json",
        **bearer(enabled["access_token"]),
    )
    assert _problem(response) == (409, "mfa_required_for_role")
    assert User.objects.get(email=account.email).mfa_enabled is True
