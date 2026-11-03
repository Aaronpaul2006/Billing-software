"""The setup checklist (H.2): GET /tenant/setup."""

from typing import Any

import pytest
from rest_framework.test import APIClient

from tests.factories import Member, add_client, add_member, make_party, make_tenant, owner_member
from tests.payments.test_payments import Money

pytestmark = pytest.mark.django_db


def _setup(member: Member) -> Any:
    return APIClient().get(
        "/api/v1/tenant/setup", HTTP_AUTHORIZATION=f"Bearer {member.access_token}"
    )


def test_a_new_business_has_only_its_gst_registration() -> None:
    owner = owner_member(make_tenant("New Builders"))
    r = _setup(owner)
    assert r.status_code == 200, r.content
    assert r.json() == {
        "gst_registration": True,  # made with the business in these tests
        "number_series": False,
        "client": False,
        "project": False,
        "first_bill": False,
        "team": False,
        "complete": False,
    }


def test_each_step_counts_once_done() -> None:
    m = Money()  # series, a client and a project
    assert _setup(m.owner).json()["first_bill"] is False
    m.create()  # a draft is not a bill yet
    assert _setup(m.owner).json()["first_bill"] is False
    m.invoice()
    add_client(m.t, m.client)  # a portal user is not team
    data = _setup(m.owner).json()
    assert data["first_bill"] is True
    assert data["team"] is False
    add_member(m.t, "ACCOUNTANT")
    assert _setup(m.owner).json() == {
        "gst_registration": True,
        "number_series": True,
        "client": True,
        "project": True,
        "first_bill": True,
        "team": True,
        "complete": True,
    }


def test_any_member_may_read_it_but_not_a_client() -> None:
    t = make_tenant()
    assert _setup(add_member(t, "SITE_ENGINEER")).status_code == 200
    assert _setup(add_client(t, make_party(t))).status_code == 403


def test_another_tenant_is_not_counted() -> None:
    Money().invoice()  # a busy tenant
    assert _setup(owner_member(make_tenant("Empty Co"))).json()["first_bill"] is False
