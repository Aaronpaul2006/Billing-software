"""Business profile, GST registrations and number series (Phase 1.2)."""

import uuid
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.tenants.models import DocumentSeries, GstRegistration
from tests.db.seed import issued_invoice, seed_tenant
from tests.factories import (
    Member,
    TenantFixture,
    add_member,
    gstin,
    make_tenant,
    owner_member,
    session_for,
)

pytestmark = pytest.mark.django_db

ADDRESS_32 = {"line1": "12 MG Road", "city": "Kochi", "state_code": "32", "pincode": "682016"}
ADDRESS_29 = {"line1": "1 Brigade Rd", "city": "Bengaluru", "state_code": "29", "pincode": "560001"}


@pytest.fixture
def tenant() -> TenantFixture:
    return make_tenant("Nair Constructions")


@pytest.fixture
def owner(tenant: TenantFixture) -> Member:
    return owner_member(tenant)


def h(member: Member | str, **extra: str) -> dict[str, Any]:
    token = member if isinstance(member, str) else member.access_token
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", **{f"HTTP_{k}": v for k, v in extra.items()}}


def problem(response: Any) -> tuple[int, str]:
    body = response.json()
    code = body["errors"][0]["code"] if body.get("code") == "validation_error" else body["code"]
    return response.status_code, code


# --- business profile ---------------------------------------------------------------


def test_every_member_reads_the_profile_with_an_etag(tenant: TenantFixture) -> None:
    viewer = add_member(tenant, "VIEWER")
    response = APIClient().get("/api/v1/tenant", **h(viewer))
    assert response.status_code == 200
    assert response.json()["legal_name"] == "Nair Constructions"
    assert response["ETag"] == '"v1"'


def test_profile_update_uses_optimistic_locking(tenant: TenantFixture) -> None:
    admin = add_member(tenant, "ADMIN")
    api = APIClient()
    change = {"trade_name": "Nair Builders", "pan": "aaaca1234a", "timezone": "Asia/Kolkata"}

    missing = api.patch("/api/v1/tenant", change, format="json", **h(admin))
    assert problem(missing) == (428, "if_match_required")

    ok = api.patch("/api/v1/tenant", change, format="json", **h(admin, IF_MATCH='"v1"'))
    assert ok.status_code == 200, ok.content
    assert ok["ETag"] == '"v2"'
    assert ok.json()["pan"] == "AAACA1234A"

    stale = api.patch(
        "/api/v1/tenant", {"trade_name": "Late edit"}, format="json", **h(admin, IF_MATCH='"v1"')
    )
    assert problem(stale) == (412, "stale_version")
    assert stale.json()["current"]["trade_name"] == "Nair Builders"
    assert stale.json()["current"]["version"] == 2


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"pan": "ABCDE1234F"}, "invalid_pan"),  # 4th letter D is not a holder type
        ({"timezone": "Mars/Olympus"}, "invalid_choice"),
        ({"legal_name": ""}, "blank"),
    ],
)
def test_profile_validation(tenant: TenantFixture, change: dict[str, str], code: str) -> None:
    response = APIClient().patch(
        "/api/v1/tenant", change, format="json", **h(owner_member(tenant), IF_MATCH='"v1"')
    )
    assert problem(response) == (422, code)


def test_only_owner_and_admin_change_the_profile(tenant: TenantFixture) -> None:
    accountant = add_member(tenant, "ACCOUNTANT")
    response = APIClient().patch(
        "/api/v1/tenant", {"trade_name": "x"}, format="json", **h(accountant, IF_MATCH='"v1"')
    )
    assert problem(response) == (403, "permission_denied")


# --- GST registrations ---------------------------------------------------------------


def _register(member: Member, **body: Any) -> Any:
    payload = {
        "registration_type": "REGULAR",
        "gstin": gstin("32"),
        "legal_name": "Nair Constructions",
        "address": ADDRESS_32,
        **body,
    }
    return APIClient().post("/api/v1/gst-registrations", payload, format="json", **h(member))


def test_register_a_gstin(owner: Member) -> None:
    response = _register(owner, gstin=gstin("32").lower())
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["gstin"] == gstin("32")
    assert body["state_code"] == "32"
    assert body["state_name"] == "Kerala"
    assert response["ETag"] == '"v1"'


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"gstin": gstin("32")[:-1] + "0"}, "invalid_gstin"),  # check digit typo
        ({"registration_type": "UNREGISTERED"}, "gstin_not_allowed"),
        ({"gstin": None}, "required"),
        ({"address": ADDRESS_29}, "state_mismatch"),
        ({"address": {**ADDRESS_32, "pincode": "012345"}}, "invalid_pincode"),
    ],
)
def test_registration_validation(owner: Member, body: dict[str, Any], code: str) -> None:
    assert problem(_register(owner, **body)) == (422, code)


def test_unregistered_needs_a_state_and_no_gstin(owner: Member) -> None:
    response = _register(owner, registration_type="UNREGISTERED", gstin=None, state_code="32")
    assert response.status_code == 201, response.content
    assert response.json()["gstin"] is None


def test_gstin_is_unique_and_must_carry_the_business_pan(
    tenant: TenantFixture, owner: Member
) -> None:
    assert _register(owner).status_code == 201
    assert problem(_register(owner)) == (422, "gstin_taken")

    api = APIClient()
    api.patch("/api/v1/tenant", {"pan": "AAACA1234A"}, format="json", **h(owner, IF_MATCH='"v1"'))
    other_pan = _register(owner, gstin=gstin("29", pan="AAACB5678B"), address=ADDRESS_29)
    assert problem(other_pan) == (422, "pan_mismatch")


def test_exactly_one_default(tenant: TenantFixture, owner: Member) -> None:
    created = _register(owner, is_default=True).json()
    with tenant_context(tenant.tenant_id, tenant.user_id):
        defaults = list(
            GstRegistration.objects.filter(is_default=True).values_list("id", flat=True)
        )
    assert [str(d) for d in defaults] == [created["id"]]

    url = f"/api/v1/gst-registrations/{created['id']}"
    api = APIClient()
    for change in ({"is_default": False}, {"is_active": False}):
        response = api.patch(url, change, format="json", **h(owner, IF_MATCH='"v1"'))
        assert problem(response) == (409, "default_required")


def test_gstin_type_and_state_cannot_change(owner: Member) -> None:
    created = _register(owner).json()
    response = APIClient().patch(
        f"/api/v1/gst-registrations/{created['id']}",
        {"gstin": gstin("29"), "registration_type": "COMPOSITION", "trade_name": "NC"},
        format="json",
        **h(owner, IF_MATCH='"v1"'),
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["gstin"], body["registration_type"], body["trade_name"]) == (
        gstin("32"),
        "REGULAR",
        "NC",
    )


# --- number series -------------------------------------------------------------------


def _series(member: Member | str, registration: str, **body: Any) -> Any:
    payload = {
        "gst_registration_id": registration,
        "doc_type": "TAX_INVOICE",
        "fy_start_year": 2026,
        "prefix": "INV/",
        **body,
    }
    return APIClient().post("/api/v1/document-series", payload, format="json", **h(member))


def test_create_series_and_preview_the_next_number(tenant: TenantFixture, owner: Member) -> None:
    response = _series(owner, str(tenant.registration_id), prefix="KL/INV/", next_number=42)
    assert response.status_code == 201, response.content
    assert response.json()["next_doc_number"] == "KL/INV/0042"


def test_one_active_series_per_registration_type_and_year(
    tenant: TenantFixture, owner: Member
) -> None:
    reg = str(tenant.registration_id)
    assert _series(owner, reg).status_code == 201
    assert problem(_series(owner, reg, prefix="B/")) == (409, "active_series_exists")
    assert _series(owner, reg, prefix="B/", is_active=False).status_code == 201
    assert problem(_series(owner, reg, is_active=False)) == (409, "series_exists")
    assert _series(owner, reg, fy_start_year=2027).status_code == 201


def test_series_rules(tenant: TenantFixture, owner: Member) -> None:
    composition = _register(
        owner, registration_type="COMPOSITION", gstin=gstin("29"), address=ADDRESS_29
    ).json()["id"]
    reg = str(tenant.registration_id)
    assert problem(_series(owner, composition)) == (422, "doc_type_not_allowed")
    assert _series(owner, composition, doc_type="BILL_OF_SUPPLY").status_code == 201
    assert problem(_series(owner, reg, prefix="ABCDEFGHIJ", pad_width=7)) == (422, "too_long")
    assert problem(_series(owner, str(uuid.uuid4()))) == (422, "not_found")


def test_series_locked_once_numbers_were_issued() -> None:
    seeded = seed_tenant("S", gstin("32"), "32")
    token = session_for(seeded.tenant, seeded.user)
    url = f"/api/v1/document-series/{seeded.series}"
    api = APIClient()

    renumbered = api.patch(url, {"next_number": 100}, format="json", **h(token, IF_MATCH='"v1"'))
    assert renumbered.status_code == 200
    assert renumbered.json()["next_doc_number"] == "INV/0100"

    with tenant_context(seeded.tenant, seeded.user):
        issued_invoice(seeded)
    locked = api.patch(url, {"prefix": "NEW/"}, format="json", **h(token, IF_MATCH='"v2"'))
    assert problem(locked) == (409, "series_in_use")
    retired = api.patch(url, {"is_active": False}, format="json", **h(token, IF_MATCH='"v2"'))
    assert retired.status_code == 200
    with tenant_context(seeded.tenant, seeded.user):
        assert DocumentSeries.objects.get(pk=seeded.series).prefix == "INV/"


def test_series_list_filters(tenant: TenantFixture, owner: Member) -> None:
    reg = str(tenant.registration_id)
    _series(owner, reg)
    _series(owner, reg, doc_type="QUOTATION", prefix="Q/")
    _series(owner, reg, doc_type="PROFORMA", prefix="P/")
    response = APIClient().get(
        "/api/v1/document-series", {"doc_type": "TAX_INVOICE,QUOTATION"}, **h(owner)
    )
    assert sorted(s["doc_type"] for s in response.json()["results"]) == [
        "QUOTATION",
        "TAX_INVOICE",
    ]


def test_incomplete_stored_address_is_still_readable() -> None:
    seeded = seed_tenant("S", gstin("32"), "32")  # raw SQL seed stores address '{}'
    token = session_for(seeded.tenant, seeded.user)
    response = APIClient().get(f"/api/v1/gst-registrations/{seeded.reg}", **h(token))
    assert response.status_code == 200
    assert response.json()["address"] == {}
