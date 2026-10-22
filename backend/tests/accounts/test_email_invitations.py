"""Invitations by email for people with no account yet (K.2)."""

import re
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import EmailInvitation, Membership, User
from apps.core.tenancy import tenant_context, user_context
from tests.factories import TenantFixture, add_member, make_tenant, owner_member

pytestmark = pytest.mark.django_db

PASSWORD = "a long enough passphrase"


@pytest.fixture
def api() -> APIClient:
    client = APIClient()
    client.default_format = "json"
    return client


@pytest.fixture
def company() -> TenantFixture:
    return make_tenant("Nair Constructions")


def _as(token: str) -> dict[str, Any]:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def _problem(response: Any) -> tuple[int, str]:
    body = response.json()
    code = body["errors"][0]["code"] if body["code"] == "validation_error" else body["code"]
    return response.status_code, code


def _link_token(message: Any) -> str:
    link = re.search(r"https://app\.example\.test/join\?\S+", str(message.body))
    assert link, message.body
    return parse_qs(urlparse(link.group(0)).query)["token"][0]


def _invite(
    api: APIClient,
    token: str,
    run: Any,
    email: str = "newcomer@example.com",
    role: str = "ACCOUNTANT",
) -> Any:
    with run(execute=True):
        return api.post("/api/v1/email-invitations", {"email": email, "role": role}, **_as(token))


def test_invite_then_join_and_sign_in(
    api: APIClient, company: TenantFixture, django_capture_on_commit_callbacks: Any
) -> None:
    owner = owner_member(company)
    created = _invite(api, owner.access_token, django_capture_on_commit_callbacks)
    assert created.status_code == 201, created.content
    body = created.json()
    assert (body["email"], body["role"], body["status"], body["expired"]) == (
        "newcomer@example.com",
        "ACCOUNTANT",
        "PENDING",
        False,
    )
    message = mail.outbox[-1]
    assert message.to == ["newcomer@example.com"]
    assert "invited you to Nair Constructions" in message.subject
    assert "join Nair Constructions as accountant" in str(message.body)
    token = _link_token(message)

    listed = api.get("/api/v1/email-invitations", **_as(owner.access_token)).json()["results"]
    assert [x["email"] for x in listed] == ["newcomer@example.com"]
    again = _invite(api, owner.access_token, django_capture_on_commit_callbacks)
    assert _problem(again) == (409, "already_invited")

    details = api.get("/api/v1/auth/join", {"token": token}).json()
    assert (details["email"], details["legal_name"], details["role"]) == (
        "newcomer@example.com",
        "Nair Constructions",
        "ACCOUNTANT",
    )
    weak = api.post("/api/v1/auth/join", {"token": token, "full_name": "Ravi", "password": "short"})
    assert _problem(weak) == (422, "weak_password")

    joined = api.post(
        "/api/v1/auth/join",
        {"token": token, "full_name": "Ravi Kumar", "password": PASSWORD, "client": "mobile"},
    )
    assert joined.status_code == 201, joined.content
    tokens = joined.json()
    assert (tokens["role"], tokens["tenant_id"]) == ("ACCOUNTANT", str(company.tenant_id))
    user = User.objects.get(email="newcomer@example.com")
    assert user.email_verified_at is not None  # the link proved the inbox
    with tenant_context(company.tenant_id, company.user_id):
        membership = Membership.objects.get(user=user)
        assert (membership.role, membership.status) == ("ACCOUNTANT", "ACTIVE")
        assert EmailInvitation.objects.get(pk=body["id"]).status == "ACCEPTED"
    me = api.get("/api/v1/me", **_as(tokens["access_token"])).json()
    assert [m["legal_name"] for m in me["memberships"]] == ["Nair Constructions"]

    second = api.post(
        "/api/v1/auth/join", {"token": token, "full_name": "Ravi", "password": PASSWORD}
    )
    assert _problem(second) == (409, "account_exists")


def test_who_may_invite_whom(
    api: APIClient, company: TenantFixture, django_capture_on_commit_callbacks: Any
) -> None:
    admin = add_member(company, "ADMIN")
    accountant = add_member(company, "ACCOUNTANT")
    run = django_capture_on_commit_callbacks
    assert _problem(_invite(api, admin.access_token, run, role="OWNER")) == (
        403,
        "owner_protected",
    )
    assert _invite(api, accountant.access_token, run).status_code == 403
    taken = _invite(api, admin.access_token, run, email=User.objects.get(pk=company.user_id).email)
    assert _problem(taken) == (422, "has_account")


def test_withdraw_and_send_again(
    api: APIClient, company: TenantFixture, django_capture_on_commit_callbacks: Any
) -> None:
    owner = owner_member(company)
    invitation = _invite(api, owner.access_token, django_capture_on_commit_callbacks).json()
    token = _link_token(mail.outbox[-1])
    url = f"/api/v1/email-invitations/{invitation['id']}"
    with tenant_context(company.tenant_id, company.user_id):  # the link ran out
        EmailInvitation.objects.filter(pk=invitation["id"]).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
    with django_capture_on_commit_callbacks(execute=True):
        resent = api.post(f"{url}/resend", **_as(owner.access_token))
    assert resent.status_code == 200
    assert resent.json()["expired"] is False  # good for another 7 days
    assert len(mail.outbox) == 2
    assert api.delete(url, **_as(owner.access_token)).status_code == 204
    assert _problem(api.delete(url, **_as(owner.access_token))) == (409, "not_pending")
    refused = api.post(
        "/api/v1/auth/join", {"token": token, "full_name": "X", "password": PASSWORD}
    )
    assert _problem(refused) == (422, "link_invalid")
    assert not User.objects.filter(email="newcomer@example.com").exists()  # rolled back


def test_expired_and_tampered_links(
    api: APIClient, company: TenantFixture, django_capture_on_commit_callbacks: Any
) -> None:
    owner = owner_member(company)
    invitation = _invite(api, owner.access_token, django_capture_on_commit_callbacks).json()
    token = _link_token(mail.outbox[-1])
    assert _problem(api.get("/api/v1/auth/join", {"token": token[:-3] + "xyz"})) == (
        422,
        "link_invalid",
    )
    with tenant_context(company.tenant_id, company.user_id):
        EmailInvitation.objects.filter(pk=invitation["id"]).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
    assert _problem(api.get("/api/v1/auth/join", {"token": token})) == (422, "link_expired")
    listed = api.get("/api/v1/email-invitations", **_as(owner.access_token)).json()["results"]
    assert listed[0]["expired"] is True  # still listed: "send again" renews it


def test_signing_up_the_normal_way_finds_the_invitation(
    api: APIClient, company: TenantFixture, django_capture_on_commit_callbacks: Any
) -> None:
    owner = owner_member(company)
    invitation = _invite(
        api, owner.access_token, django_capture_on_commit_callbacks, email="later@example.com"
    ).json()
    signup = api.post(
        "/api/v1/auth/signup",
        {
            "email": "Later@Example.com",
            "password": PASSWORD,
            "full_name": "Later Person",
            "business_name": "Own Business",
        },
    )
    assert signup.status_code == 201, signup.content
    token = signup.json()["access_token"]
    pending = api.get("/api/v1/invitations", **_as(token)).json()["results"]
    assert [(p["legal_name"], p["role"]) for p in pending] == [("Nair Constructions", "ACCOUNTANT")]
    with tenant_context(company.tenant_id, company.user_id):
        assert EmailInvitation.objects.get(pk=invitation["id"]).status == "ACCEPTED"
    accepted = api.post(f"/api/v1/invitations/{pending[0]['id']}/accept", **_as(token))
    assert accepted.status_code == 200, accepted.content
    user = User.objects.get(email="later@example.com")
    with user_context(user.pk):
        assert Membership.objects.filter(
            user=user, tenant_id=company.tenant_id, status="ACTIVE"
        ).exists()
