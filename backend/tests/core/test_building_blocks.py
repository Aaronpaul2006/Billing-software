"""Money fields, optimistic locking, pagination and idempotency keys."""

import threading
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.db import connections
from django.test import override_settings
from django.utils import timezone
from rest_framework import serializers
from rest_framework.test import APIClient

from apps.catalog.models import CatalogItem
from apps.core.errors import PreconditionFailed, PreconditionRequired
from apps.core.fields import MoneyField, PercentField, QuantityField
from apps.core.models import IdempotencyKey
from apps.core.tenancy import tenant_context
from apps.core.versioning import expected_version, update_versioned
from apps.parties.models import Party
from tests.factories import Member, TenantFixture, make_party, make_tenant, owner_member

URLS = "tests.core.urls"


def _bearer(member: Member) -> dict[str, Any]:
    return {"HTTP_AUTHORIZATION": f"Bearer {member.access_token}"}


# --- money fields ---------------------------------------------------------------------


class _Amounts(serializers.Serializer[Any]):
    amount = MoneyField()
    quantity = QuantityField(required=False)
    rate = PercentField(required=False)


@pytest.mark.parametrize("raw", [11800, 11800.5, True])
def test_money_rejects_json_numbers(raw: object) -> None:
    s = _Amounts(data={"amount": raw})
    assert not s.is_valid()
    assert s.errors["amount"][0].code == "not_a_string"


def test_money_quantity_and_percent_parse_strings_exactly() -> None:
    s = _Amounts(data={"amount": "11800.10", "quantity": "42.125", "rate": "18.00"})
    assert s.is_valid(), s.errors
    assert s.validated_data == {
        "amount": Decimal("11800.10"),
        "quantity": Decimal("42.125"),
        "rate": Decimal("18.00"),
    }
    assert _Amounts(instance={"amount": Decimal("5")}).data["amount"] == "5.00"


@pytest.mark.parametrize(
    ("data", "field", "code"),
    [
        ({"amount": "1.005"}, "amount", "max_decimal_places"),
        ({"amount": "1", "quantity": "1.0001"}, "quantity", "max_decimal_places"),
        ({"amount": "1", "rate": "100.01"}, "rate", "max_value"),
        ({"amount": "1", "rate": "-1"}, "rate", "min_value"),
        ({"amount": "abc"}, "amount", "invalid"),
    ],
)
def test_precision_and_range(data: dict[str, str], field: str, code: str) -> None:
    s = _Amounts(data=data)
    assert not s.is_valid()
    assert s.errors[field][0].code == code


# --- optimistic locking -------------------------------------------------------------------


class _Req:
    def __init__(self, if_match: str | None) -> None:
        self.headers = {"If-Match": if_match} if if_match else {}


def test_if_match_is_required_and_parsed() -> None:
    with pytest.raises(PreconditionRequired):
        expected_version(_Req(None))  # type: ignore[arg-type]
    assert expected_version(_Req('"v7"')) == 7  # type: ignore[arg-type]
    assert expected_version(_Req('W/"v7"')) == 7  # type: ignore[arg-type]
    with pytest.raises(PreconditionFailed):
        expected_version(_Req("7"))  # type: ignore[arg-type]


@pytest.mark.django_db
def test_compare_and_set_rejects_a_stale_version() -> None:
    t = make_tenant()
    party = make_party(t)
    with tenant_context(t.tenant_id, t.user_id):
        assert party.version == 1

        def current() -> dict[str, Any]:
            return {"display_name": Party.objects.get(pk=party.pk).display_name}

        assert update_versioned(Party.objects, party.pk, 1, current, display_name="First") == 2
        with pytest.raises(PreconditionFailed) as exc_info:
            update_versioned(Party.objects, party.pk, 1, current, display_name="Second")
        assert exc_info.value.extra == {"current": {"display_name": "First"}}
        assert Party.objects.get(pk=party.pk).version == 2


# --- pagination -----------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=URLS)
def test_cursor_pagination_walks_all_rows_once() -> None:
    t = make_tenant()
    owner = owner_member(t)
    with tenant_context(t.tenant_id, t.user_id):
        for name in ["a", "b", "c", "d", "e"]:
            CatalogItem.objects.create(name=name)
    api, seen, cursor = APIClient(), [], None
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        body = api.get("/api/v1/test/items/list", params, **_bearer(owner)).json()
        assert len(body["results"]) <= 2
        seen += [r["name"] for r in body["results"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == ["e", "d", "c", "b", "a"]  # newest first (UUIDv7 ids)

    by_name = api.get("/api/v1/test/items/list", {"ordering": "name"}, **_bearer(owner)).json()
    assert [r["name"] for r in by_name["results"]] == ["a", "b", "c", "d", "e"]


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=URLS)
def test_limit_is_capped_at_100() -> None:
    t = make_tenant()
    owner = owner_member(t)
    with tenant_context(t.tenant_id, t.user_id):
        CatalogItem.objects.bulk_create(
            [CatalogItem(tenant_id=t.tenant_id, name=f"item {i}") for i in range(105)]
        )
    body = APIClient().get("/api/v1/test/items/list", {"limit": 500}, **_bearer(owner)).json()
    assert len(body["results"]) == 100
    assert body["next_cursor"] is not None


# --- idempotency keys ----------------------------------------------------------------------


def _post(api: APIClient, owner: Member, body: dict[str, Any], key: str | None) -> Any:
    headers: dict[str, Any] = {"HTTP_IDEMPOTENCY_KEY": key} if key else {}
    return api.post("/api/v1/test/items", body, format="json", **_bearer(owner), **headers)


def _count(t: TenantFixture, name: str) -> int:
    with tenant_context(t.tenant_id, t.user_id):
        return CatalogItem.objects.filter(name=name).count()


@pytest.fixture
def setup() -> tuple[APIClient, TenantFixture, Member]:
    t = make_tenant()
    return APIClient(), t, owner_member(t)


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=URLS)
def test_retry_with_same_key_replays_without_running_twice(
    setup: tuple[APIClient, TenantFixture, Member],
) -> None:
    api, t, owner = setup
    key = str(uuid.uuid4())
    first = _post(api, owner, {"name": "Cement", "default_rate": "380.00"}, key)
    retry = _post(api, owner, {"name": "Cement", "default_rate": "380.00"}, key)
    assert first.status_code == retry.status_code == 201
    assert retry.json() == first.json()
    assert retry["Idempotent-Replayed"] == "true"
    assert "Idempotent-Replayed" not in first
    assert _count(t, "Cement") == 1


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=URLS)
def test_key_required_and_cannot_be_reused_for_another_request(
    setup: tuple[APIClient, TenantFixture, Member],
) -> None:
    api, t, owner = setup
    missing = _post(api, owner, {"name": "Sand"}, None)
    assert (missing.status_code, missing.json()["code"]) == (428, "idempotency_key_required")

    key = str(uuid.uuid4())
    assert _post(api, owner, {"name": "Sand"}, key).status_code == 201
    other = _post(api, owner, {"name": "Steel"}, key)
    assert other.status_code == 422
    assert other.json()["errors"][0]["code"] == "idempotency_key_reused"
    assert _count(t, "Steel") == 0


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=URLS)
def test_failed_request_leaves_no_key_so_the_retry_runs_again(
    setup: tuple[APIClient, TenantFixture, Member],
) -> None:
    api, t, owner = setup
    key = str(uuid.uuid4())
    for _ in range(2):
        failed = _post(api, owner, {"name": "fail after writing"}, key)
        assert failed.status_code == 422
        assert "Idempotent-Replayed" not in failed
    assert _count(t, "half-done") == 0  # the partial write was rolled back too
    with tenant_context(t.tenant_id, t.user_id):
        assert not IdempotencyKey.objects.filter(key=key).exists()


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=URLS)
def test_expired_key_can_be_used_again(setup: tuple[APIClient, TenantFixture, Member]) -> None:
    api, t, owner = setup
    key = str(uuid.uuid4())
    assert _post(api, owner, {"name": "Bricks"}, key).status_code == 201
    with tenant_context(t.tenant_id, t.user_id):
        IdempotencyKey.objects.filter(key=key).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
    again = _post(api, owner, {"name": "Bricks"}, key)
    assert again.status_code == 201
    assert "Idempotent-Replayed" not in again
    assert _count(t, "Bricks") == 2


@pytest.mark.usefixtures("committed_db")
@override_settings(ROOT_URLCONF=URLS)
def test_concurrent_duplicates_run_once() -> None:
    t = make_tenant()
    owner = owner_member(t)
    key, name = str(uuid.uuid4()), f"Gravel {uuid.uuid4().hex[:6]}"
    barrier = threading.Barrier(2)
    responses: list[Any] = []

    def send() -> None:
        try:
            barrier.wait(timeout=10)
            responses.append(_post(APIClient(), owner, {"name": name}, key))
        finally:
            connections.close_all()

    threads = [threading.Thread(target=send) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=30)

    assert [r.status_code for r in responses] == [201, 201]
    assert sorted(r.has_header("Idempotent-Replayed") for r in responses) == [False, True]
    assert _count(t, name) == 1
