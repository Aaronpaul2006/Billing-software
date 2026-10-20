"""Rate limits in Redis (docs/01-architecture.md §6, docs/02-api-design.md §1)."""

import logging
from collections.abc import Callable
from typing import Any

import pytest
import redis
from django.core import mail
from django.test import RequestFactory
from rest_framework.test import APIClient

from apps.core import ratelimit

from .conftest import Account, bearer

pytestmark = pytest.mark.django_db

MakeAccount = Callable[..., Account]


@pytest.fixture
def api() -> APIClient:
    client = APIClient()
    client.default_format = "json"
    return client


@pytest.fixture(autouse=True)
def _needs_redis(settings: Any) -> None:
    try:
        redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1).ping()
    except redis.RedisError:
        pytest.fail("Redis is not reachable: rate limit tests need it (docker compose up -d)")


def _login(api: APIClient, email: str, **extra: Any) -> Any:
    return api.post("/api/v1/auth/login", {"email": email, "password": "wrong-password"}, **extra)


def test_counter_counts_and_expires_with_its_window(settings: Any) -> None:
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, "login_ip": (2, 30)}
    first = ratelimit.hit("login_ip", "10.0.0.1")
    second = ratelimit.hit("login_ip", "10.0.0.1")
    third = ratelimit.hit("login_ip", "10.0.0.1")
    other = ratelimit.hit("login_ip", "10.0.0.2")
    assert first is not None
    assert second is not None
    assert third is not None
    assert other is not None
    assert (first.count, first.remaining, first.exceeded) == (1, 1, False)
    assert (second.remaining, second.exceeded) == (0, False)
    assert (third.remaining, third.exceeded) == (0, True)
    assert 1 <= third.reset <= 30
    assert other.count == 1  # counted per key


def test_login_is_limited_per_email_with_headers(api: APIClient, settings: Any) -> None:
    for i in range(5):
        response = _login(api, "Victim@Example.com" if i % 2 else "victim@example.com")
        assert response.status_code == 401
        assert response["RateLimit-Limit"] == "5"
        assert response["RateLimit-Remaining"] == str(4 - i)
    blocked = _login(api, "victim@example.com")
    assert blocked.status_code == 429
    body = blocked.json()
    assert body["code"] == "rate_limited"
    assert body["detail"].startswith("Too many attempts. Try again in ")
    assert 1 <= body["retry_after"] <= 60
    assert blocked["Retry-After"] == str(body["retry_after"])
    assert blocked["RateLimit-Remaining"] == "0"
    # Another account from the same address is not blocked by this one.
    assert _login(api, "someone-else@example.com").status_code == 401


def test_login_is_limited_per_ip(api: APIClient, settings: Any) -> None:
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, "login_ip": (3, 60)}
    for i in range(3):
        assert _login(api, f"user{i}@example.com").status_code == 401
    assert _login(api, "user9@example.com").status_code == 429
    # A different client address has its own counter.
    assert _login(api, "user9@example.com", REMOTE_ADDR="203.0.113.7").status_code == 401


def test_forgot_password_sends_at_most_three_emails_an_hour(
    api: APIClient, make_account: MakeAccount, django_capture_on_commit_callbacks: Any
) -> None:
    account = make_account()
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        codes = [
            api.post("/api/v1/auth/password/forgot", {"email": account.email}).status_code
            for _ in range(4)
        ]
    assert codes == [204, 204, 204, 429]
    assert len(mail.outbox) == 3


def test_resend_verification_is_limited_per_user(api: APIClient, make_account: MakeAccount) -> None:
    account = make_account()
    codes = [
        api.post("/api/v1/auth/verify-email/resend", **bearer(account.access)).status_code
        for _ in range(4)
    ]
    assert codes == [204, 204, 204, 429]


def test_signed_in_requests_are_limited_per_user(
    api: APIClient, make_account: MakeAccount, settings: Any
) -> None:
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, "api_user": (3, 60)}
    busy, quiet = make_account(), make_account()
    seen = [api.get("/api/v1/me", **bearer(busy.access)) for _ in range(3)]
    assert [r.status_code for r in seen] == [200, 200, 200]
    assert [r["RateLimit-Remaining"] for r in seen] == ["2", "1", "0"]
    blocked = api.get("/api/v1/me", **bearer(busy.access))
    assert blocked.status_code == 429
    assert blocked["Content-Type"] == "application/problem+json"
    assert blocked.json()["code"] == "rate_limited"
    assert blocked["Retry-After"]
    assert api.get("/api/v1/me", **bearer(quiet.access)).status_code == 200


def test_requests_are_allowed_when_redis_is_down(
    api: APIClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    dead = redis.Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.1)
    monkeypatch.setattr(ratelimit, "_script", lambda: dead.register_script(ratelimit._HIT))
    with caplog.at_level(logging.WARNING, logger="apps.core.ratelimit"):
        for _ in range(7):
            response = _login(api, "victim@example.com")
            assert response.status_code == 401
            assert "RateLimit-Limit" not in response
    assert "Redis unreachable" in caplog.text


def test_client_ip_trusts_only_the_configured_proxies(settings: Any) -> None:
    factory = RequestFactory()
    forged = factory.get(
        "/", REMOTE_ADDR="172.16.0.5", HTTP_X_FORWARDED_FOR="1.2.3.4, 198.51.100.9"
    )
    settings.TRUSTED_PROXY_COUNT = 0
    assert ratelimit.client_ip(forged) == "172.16.0.5"
    settings.TRUSTED_PROXY_COUNT = 1  # the load balancer added 198.51.100.9
    assert ratelimit.client_ip(forged) == "198.51.100.9"
    settings.TRUSTED_PROXY_COUNT = 2
    assert ratelimit.client_ip(forged) == "1.2.3.4"
    garbage = factory.get("/", REMOTE_ADDR="172.16.0.5", HTTP_X_FORWARDED_FOR="not-an-ip")
    settings.TRUSTED_PROXY_COUNT = 1
    assert ratelimit.client_ip(garbage) == "172.16.0.5"
    direct = factory.get("/", REMOTE_ADDR="172.16.0.5")
    assert ratelimit.client_ip(direct) == "172.16.0.5"
