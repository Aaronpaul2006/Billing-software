import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pyotp
import pytest
from rest_framework.test import APIClient

from apps.accounts import services

PASSWORD = "correct horse battery staple"


@dataclass
class Account:
    email: str
    password: str
    signup: dict[str, Any]

    @property
    def access(self) -> str:
        return str(self.signup["access_token"])

    @property
    def tenant_id(self) -> str:
        return str(self.signup["tenant_id"])


def bearer(token: str) -> dict[str, Any]:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


@pytest.fixture
def api() -> APIClient:
    return APIClient()


@pytest.fixture
def make_account(api: APIClient) -> Callable[..., Account]:
    def make(business: str = "Acme Builders", **extra: Any) -> Account:
        email = f"owner-{uuid.uuid4().hex[:10]}@example.com"
        response = api.post(
            "/api/v1/auth/signup",
            {
                "email": email,
                "password": PASSWORD,
                "full_name": "Priya Nair",
                "business_name": business,
                **extra,
            },
            format="json",
        )
        assert response.status_code == 201, response.content
        return Account(email=email, password=PASSWORD, signup=response.json())

    return make


class Clock:
    """Controls the TOTP clock: each `advance()` moves to the next 30 s step,
    so a fresh code is accepted despite replay protection."""

    def __init__(self) -> None:
        self.now = time.time()

    def advance(self, seconds: float = 30) -> None:
        self.now += seconds

    def code(self, secret: str) -> str:
        return pyotp.TOTP(secret).at(int(self.now))


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    c = Clock()
    monkeypatch.setattr(services, "_clock", lambda: c.now)
    return c


def enable_mfa(api: APIClient, account: Account, clock: Clock) -> tuple[str, dict[str, Any]]:
    """Set up and enable TOTP; returns (secret, enable response body)."""
    setup = api.post("/api/v1/auth/mfa/setup", **bearer(account.access))
    assert setup.status_code == 200, setup.content
    secret = setup.json()["secret"]
    enabled = api.post(
        "/api/v1/auth/mfa/enable",
        {"code": clock.code(secret)},
        format="json",
        **bearer(account.access),
    )
    assert enabled.status_code == 200, enabled.content
    return secret, enabled.json()
