"""Tenant context: transaction-local, never leaks, enforced end to end by RLS
and composite foreign keys (docs/01-architecture.md §2.2-§2.4)."""

import uuid
from typing import Any

import pytest
from django.conf import settings
from django.db import DatabaseError, connection, transaction
from django.test import Client, override_settings

from apps.catalog.models import CatalogItem
from apps.core.tenancy import (
    TenantContextError,
    current_context,
    current_tenant_id,
    tenant_context,
)
from apps.parties.models import Party
from apps.projects.models import Project
from tests.factories import TenantFixture, make_party, make_tenant

pytestmark = pytest.mark.usefixtures("committed_db")

RLS_VIOLATION = "42501"  # insufficient_privilege: new row violates row-level security policy
FK_VIOLATION = "23503"


def _db_context() -> tuple[Any, Any]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT app_current_tenant(), app_current_user_id()")
        row = cursor.fetchone()
    assert row is not None
    return row[0], row[1]


def _sqlstate(exc: BaseException) -> str | None:
    return getattr(exc.__cause__, "sqlstate", None)


# --- tenant_context() ---------------------------------------------------------


def test_context_is_set_inside_and_gone_after_commit() -> None:
    tenant_id, user_id = uuid.uuid7(), uuid.uuid7()
    with tenant_context(tenant_id, user_id) as ctx:
        assert _db_context() == (tenant_id, user_id)
        assert current_tenant_id() == tenant_id == ctx.tenant_id
    assert current_context() is None
    with transaction.atomic():  # a fresh transaction on the same connection
        assert _db_context() == (None, None)


def test_context_cleared_when_nested_in_a_longer_transaction() -> None:
    with transaction.atomic():
        with tenant_context(uuid.uuid7()):
            pass
        # the outer transaction is still open; the tenant must not linger in it
        assert _db_context() == (None, None)


def test_reentering_same_tenant_is_allowed_switching_is_not() -> None:
    tenant_id, user_id = uuid.uuid7(), uuid.uuid7()
    with tenant_context(tenant_id, user_id):
        with tenant_context(str(tenant_id), str(user_id)):
            assert _db_context() == (tenant_id, user_id)
        with pytest.raises(TenantContextError), tenant_context(uuid.uuid7(), user_id):
            pass
        assert _db_context() == (tenant_id, user_id)


def test_current_tenant_id_raises_without_context() -> None:
    with pytest.raises(TenantContextError):
        current_tenant_id()


def test_exception_rolls_back_the_block() -> None:
    t = make_tenant()
    name = f"rolled back {uuid.uuid4().hex}"

    def write_then_fail() -> None:
        with tenant_context(t.tenant_id, t.user_id):
            CatalogItem.objects.create(tenant_id=t.tenant_id, name=name)
            raise RuntimeError

    with pytest.raises(RuntimeError):
        write_then_fail()
    with tenant_context(t.tenant_id, t.user_id):
        assert not CatalogItem.objects.filter(name=name).exists()


# --- isolation, end to end ----------------------------------------------------


@pytest.fixture
def two_tenants() -> tuple[TenantFixture, TenantFixture, Party]:
    a, b = make_tenant("Tenant A"), make_tenant("Tenant B")
    party_a = make_party(a, "A's client")
    make_party(b, "B's client")
    return a, b, party_a


def test_each_tenant_sees_only_its_own_rows(
    two_tenants: tuple[TenantFixture, TenantFixture, Party],
) -> None:
    a, b, party_a = two_tenants
    with tenant_context(a.tenant_id, a.user_id):
        assert list(Party.objects.values_list("display_name", flat=True)) == ["A's client"]
    with tenant_context(b.tenant_id, b.user_id):
        assert list(Party.objects.values_list("display_name", flat=True)) == ["B's client"]
        assert not Party.objects.filter(id=party_a.id).exists()  # forgotten filter is harmless
    with transaction.atomic():
        assert Party.objects.count() == 0  # no context: fail closed


def test_tenant_cannot_write_rows_for_another_tenant(
    two_tenants: tuple[TenantFixture, TenantFixture, Party],
) -> None:
    a, b, _ = two_tenants
    with tenant_context(b.tenant_id, b.user_id):
        with pytest.raises(DatabaseError) as exc_info, transaction.atomic():
            Party.objects.create(
                tenant_id=a.tenant_id,
                display_name="smuggled",
                gst_treatment=Party.GstTreatment.UNREGISTERED,
                created_by_id=b.user_id,
            )
        assert _sqlstate(exc_info.value) == RLS_VIOLATION


def test_tenant_cannot_update_another_tenants_rows(
    two_tenants: tuple[TenantFixture, TenantFixture, Party],
) -> None:
    a, b, party_a = two_tenants
    with tenant_context(b.tenant_id, b.user_id):
        assert Party.objects.filter(id=party_a.id).update(display_name="hijacked") == 0
    with tenant_context(a.tenant_id, a.user_id):
        assert Party.objects.get(id=party_a.id).display_name == "A's client"


def test_tenant_cannot_reference_another_tenants_rows(
    two_tenants: tuple[TenantFixture, TenantFixture, Party],
) -> None:
    """FK checks bypass RLS; only the composite (tenant_id, x_id) key stops this."""
    _, b, party_a = two_tenants
    with tenant_context(b.tenant_id, b.user_id):
        with pytest.raises(DatabaseError) as exc_info, transaction.atomic():
            Project.objects.create(
                tenant_id=b.tenant_id,
                code="P-1",
                name="Villa",
                client_party_id=party_a.id,  # tenant A's party, uuid learned somehow
                gst_registration_id=b.registration_id,
                site_state_code="32",
                created_by_id=b.user_id,
            )
        assert _sqlstate(exc_info.value) == FK_VIOLATION


# --- TenantContextMiddleware --------------------------------------------------

TEST_MIDDLEWARE = list(settings.MIDDLEWARE)
TEST_MIDDLEWARE.insert(
    TEST_MIDDLEWARE.index("apps.core.middleware.TenantContextMiddleware"),
    "tests.tenancy.urls.FakeAuthenticationMiddleware",
)


def _as(t: TenantFixture) -> dict[str, str]:
    return {"HTTP_X_TEST_PRINCIPAL": f"{t.tenant_id}:{t.user_id}"}


@override_settings(ROOT_URLCONF="tests.tenancy.urls", MIDDLEWARE=TEST_MIDDLEWARE)
def test_request_runs_in_its_principals_tenant(
    two_tenants: tuple[TenantFixture, TenantFixture, Party],
) -> None:
    a, _, _ = two_tenants
    response = Client().get("/whoami", **_as(a))  # type: ignore[arg-type]
    body = response.json()
    assert body["tenant_id"] == str(a.tenant_id)
    assert body["user_id"] == str(a.user_id)
    assert body["request_id"] == response["X-Request-ID"]
    assert body["parties_visible"] == 1


@override_settings(ROOT_URLCONF="tests.tenancy.urls", MIDDLEWARE=TEST_MIDDLEWARE)
def test_pooled_connection_does_not_leak_tenant_to_next_request(
    two_tenants: tuple[TenantFixture, TenantFixture, Party],
) -> None:
    a, b, _ = two_tenants
    client = Client()
    first = client.get("/whoami", **_as(a)).json()  # type: ignore[arg-type]
    anonymous = client.get("/whoami").json()
    other = client.get("/whoami", **_as(b)).json()  # type: ignore[arg-type]

    # Same physical connection each time (CONN_MAX_AGE), i.e. the pooled case.
    assert first["backend_pid"] == anonymous["backend_pid"] == other["backend_pid"]
    assert first["tenant_id"] == str(a.tenant_id)
    assert anonymous["tenant_id"] is None
    assert anonymous["parties_visible"] == 0
    assert other["tenant_id"] == str(b.tenant_id)
    assert other["parties_visible"] == 1


@override_settings(ROOT_URLCONF="tests.tenancy.urls", MIDDLEWARE=TEST_MIDDLEWARE)
def test_failing_view_rolls_back_its_writes(
    two_tenants: tuple[TenantFixture, TenantFixture, Party],
) -> None:
    a, _, _ = two_tenants
    name = f"never saved {uuid.uuid4().hex}"
    response = Client(raise_request_exception=False).get(
        "/write-then-fail",
        {"name": name},
        **_as(a),  # type: ignore[arg-type]
    )
    assert response.status_code == 500
    with tenant_context(a.tenant_id, a.user_id):
        assert not CatalogItem.objects.filter(name=name).exists()
