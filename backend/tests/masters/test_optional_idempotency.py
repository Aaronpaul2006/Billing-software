"""Master-data creates honour an Idempotency-Key when one is sent."""

import uuid

import pytest
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.parties.models import Party
from tests.documents.test_drafts import World

pytestmark = pytest.mark.django_db

BODY = {"display_name": "Coastal Cement", "gst_treatment": "UNREGISTERED", "is_vendor": True}


def count(w: World) -> int:
    with tenant_context(w.t.tenant_id, w.t.user_id):
        return Party.objects.filter(display_name="Coastal Cement").count()


def test_a_retried_create_with_the_same_key_is_replayed() -> None:
    w, api, key = World(), APIClient(), str(uuid.uuid4())
    first = api.post("/api/v1/parties", BODY, format="json", **w.h(IDEMPOTENCY_KEY=key))
    again = api.post("/api/v1/parties", BODY, format="json", **w.h(IDEMPOTENCY_KEY=key))
    assert (first.status_code, again.status_code) == (201, 201)
    assert again["Idempotent-Replayed"] == "true"
    assert again.json()["id"] == first.json()["id"]
    other = api.post(
        "/api/v1/parties",
        {**BODY, "display_name": "Other"},
        format="json",
        **w.h(IDEMPOTENCY_KEY=key),
    )
    assert (other.status_code, other.json()["errors"][0]["code"]) == (422, "idempotency_key_reused")
    assert count(w) == 1


def test_without_a_key_creates_as_before() -> None:
    w, api = World(), APIClient()
    for _ in range(2):
        assert api.post("/api/v1/parties", BODY, format="json", **w.h()).status_code == 201
    assert count(w) == 2
