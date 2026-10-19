"""Parties, projects, BOQ items and catalog (Phase 1.3)."""

import uuid
from datetime import date
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.documents.models import Document, DocumentLine
from apps.tenants.models import GstRegistration
from tests.factories import Member, TenantFixture, add_member, gstin, make_tenant, owner_member

pytestmark = pytest.mark.django_db

SITE_32 = {"line1": "Plot 7", "city": "Kochi", "state_code": "32", "pincode": "682030"}


@pytest.fixture
def t() -> TenantFixture:
    return make_tenant()


@pytest.fixture
def owner(t: TenantFixture) -> Member:
    return owner_member(t)


def h(m: Member, **extra: str) -> dict[str, Any]:
    return {
        "HTTP_AUTHORIZATION": f"Bearer {m.access_token}",
        **{f"HTTP_{k}": v for k, v in extra.items()},
    }


def problem(r: Any) -> tuple[int, str]:
    b = r.json()
    return r.status_code, (b["errors"][0]["code"] if b["code"] == "validation_error" else b["code"])


def post(m: Member, url: str, body: dict[str, Any]) -> Any:
    return APIClient().post(url, body, format="json", **h(m))


def patch(m: Member, url: str, body: dict[str, Any], version: int = 1) -> Any:
    return APIClient().patch(url, body, format="json", **h(m, IF_MATCH=f'"v{version}"'))


def party(m: Member, **body: Any) -> Any:
    return post(
        m,
        "/api/v1/parties",
        {"display_name": "Skyline Developers", "gst_treatment": "UNREGISTERED", **body},
    )


# --- parties -------------------------------------------------------------------------


def test_registered_party_takes_state_and_pan_from_its_gstin(owner: Member) -> None:
    r = party(owner, gst_treatment="REGISTERED", gstin=gstin("29", pan="AAACS4321K").lower())
    assert r.status_code == 201, r.content
    body = r.json()
    assert (body["gstin"], body["state_code"], body["pan"]) == (
        gstin("29", pan="AAACS4321K"),
        "29",
        "AAACS4321K",
    )
    assert body["state_name"] == "Karnataka"
    assert r["ETag"] == '"v1"'


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"gst_treatment": "REGISTERED"}, "required"),
        ({"gst_treatment": "CONSUMER", "gstin": gstin("32")}, "gstin_not_allowed"),
        ({"gst_treatment": "REGISTERED", "gstin": gstin("32")[:-1] + "0"}, "invalid_gstin"),
        (
            {"gst_treatment": "REGISTERED", "gstin": gstin("32"), "pan": "AAACZ9999Z"},
            "pan_mismatch",
        ),
        ({"is_customer": False, "is_vendor": False}, "no_role"),
        (
            {"billing_address": {"line1": "x", "city": "Kochi", "state_code": "32"}},
            "invalid_pincode",
        ),
        ({"phone": "12345"}, "invalid"),
    ],
)
def test_party_validation(owner: Member, body: dict[str, Any], code: str) -> None:
    assert problem(party(owner, **body)) == (422, code)


def test_overseas_address_needs_no_state_or_pin(owner: Member) -> None:
    r = party(
        owner,
        gst_treatment="OVERSEAS",
        billing_address={"line1": "1 Marina Blvd", "city": "Singapore", "country": "sg"},
    )
    assert r.status_code == 201, r.content
    assert r.json()["billing_address"]["country"] == "SG"


def test_patch_validates_the_merged_party(owner: Member) -> None:
    created = party(owner, gst_treatment="REGISTERED", gstin=gstin("32")).json()
    url = f"/api/v1/parties/{created['id']}"
    assert problem(patch(owner, url, {"gst_treatment": "CONSUMER"})) == (422, "gstin_not_allowed")
    ok = patch(owner, url, {"gst_treatment": "CONSUMER", "gstin": None})
    assert ok.status_code == 200, ok.content
    assert ok.json()["gst_treatment"] == "CONSUMER"
    assert ok["ETag"] == '"v2"'


def test_search_and_filters(owner: Member) -> None:
    party(owner, display_name="Skyline Developers")
    party(owner, display_name="Coastal Cement", is_customer=False, is_vendor=True)
    reg = party(
        owner, display_name="Metro Infra", gst_treatment="REGISTERED", gstin=gstin("32")
    ).json()
    api = APIClient()

    def names(**q: str) -> list[str]:
        return sorted(
            p["display_name"] for p in api.get("/api/v1/parties", q, **h(owner)).json()["results"]
        )

    assert names(q="sky") == ["Skyline Developers"]
    assert names(q=reg["gstin"].lower()) == ["Metro Infra"]
    assert names(is_vendor="true") == ["Coastal Cement"]


def test_roles_for_master_data(t: TenantFixture) -> None:
    engineer, viewer = add_member(t, "SITE_ENGINEER"), add_member(t, "VIEWER")
    assert problem(party(engineer)) == (403, "permission_denied")
    assert APIClient().get("/api/v1/parties", **h(viewer)).status_code == 200


# --- projects -------------------------------------------------------------------------


def project(m: Member, t: TenantFixture, client_id: str, **body: Any) -> Any:
    return post(
        m,
        "/api/v1/projects",
        {
            "code": "VILLA-1",
            "name": "Villa at Kakkanad",
            "client_party_id": client_id,
            "gst_registration_id": str(t.registration_id),
            "site_state_code": "32",
            "site_address": SITE_32,
            "contract_value": "4500000.00",
            "retention_pct": "5.00",
            **body,
        },
    )


def test_create_project_with_money_as_strings(t: TenantFixture, owner: Member) -> None:
    client = party(owner).json()["id"]
    r = project(owner, t, client, mobilisation_advance="200000")
    assert r.status_code == 201, r.content
    body = r.json()
    assert (body["contract_value"], body["retention_pct"], body["mobilisation_advance"]) == (
        "4500000.00",
        "5.00",
        "200000.00",
    )
    assert problem(project(owner, t, client, code="V2", contract_value=4500000)) == (
        422,
        "not_a_string",
    )


def test_project_reference_rules(t: TenantFixture, owner: Member) -> None:
    vendor = party(owner, is_customer=False, is_vendor=True).json()["id"]
    client = party(owner).json()["id"]
    assert problem(project(owner, t, vendor)) == (422, "not_a_customer")
    assert problem(project(owner, t, str(uuid.uuid4()))) == (422, "not_found")
    with tenant_context(t.tenant_id, t.user_id):
        GstRegistration.objects.filter(pk=t.registration_id).update(is_active=False)
    assert problem(project(owner, t, client)) == (422, "inactive")


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"start_date": "2026-11-01", "end_date": "2026-10-01"}, "invalid_dates"),
        ({"site_state_code": "29"}, "state_mismatch"),  # site address is in 32
        ({"retention_pct": "101"}, "max_value"),
        ({"code": "has space"}, "invalid"),
    ],
)
def test_project_validation(
    t: TenantFixture, owner: Member, body: dict[str, Any], code: str
) -> None:
    client = party(owner).json()["id"]
    assert problem(project(owner, t, client, **body)) == (422, code)


def test_project_code_is_unique(t: TenantFixture, owner: Member) -> None:
    client = party(owner).json()["id"]
    assert project(owner, t, client).status_code == 201
    assert problem(project(owner, t, client)) == (409, "code_taken")


def _draft_document(t: TenantFixture, project_id: str, client_id: str) -> Document:
    with tenant_context(t.tenant_id, t.user_id):
        doc: Document = Document.objects.create(
            doc_type="QUOTATION",
            gst_registration_id=t.registration_id,
            doc_date=date(2026, 10, 19),
            party_id=client_id,
            project_id=project_id,
            place_of_supply="32",
            supply_type="INTRA_STATE",
            created_by_id=t.user_id,
        )
    return doc


def test_billing_fields_lock_once_documents_exist(t: TenantFixture, owner: Member) -> None:
    client = party(owner).json()["id"]
    created = project(owner, t, client).json()
    url = f"/api/v1/projects/{created['id']}"
    _draft_document(t, created["id"], client)
    assert problem(patch(owner, url, {"site_state_code": "29", "site_address": None})) == (
        409,
        "project_in_use",
    )
    assert patch(owner, url, {"name": "Villa, phase 2"}).status_code == 200


# --- BOQ items ------------------------------------------------------------------------


def boq(m: Member, project_id: str, **body: Any) -> Any:
    return post(
        m,
        f"/api/v1/projects/{project_id}/boq-items",
        {
            "item_code": "2.1.3",
            "description": "RCC M25 slab",
            "unit": "cum",
            "sac_hsn": "9954",
            "contract_qty": "120.500",
            "rate": "6800.00",
            **body,
        },
    )


def test_boq_items(t: TenantFixture, owner: Member) -> None:
    client = party(owner).json()["id"]
    proj = project(owner, t, client).json()["id"]
    engineer = add_member(t, "SITE_ENGINEER")

    created = boq(engineer, proj)  # site engineers edit the BOQ (boq.edit)
    assert created.status_code == 201, created.content
    assert (created.json()["contract_qty"], created.json()["gst_rate"]) == ("120.500", "18.00")
    assert problem(boq(owner, proj)) == (409, "item_code_taken")
    assert problem(boq(owner, proj, item_code="2.1.4", gst_rate="51")) == (422, "max_value")

    listed = APIClient().get(f"/api/v1/projects/{proj}/boq-items", **h(owner)).json()["results"]
    assert [i["item_code"] for i in listed] == ["2.1.3"]
    missing = APIClient().get(f"/api/v1/projects/{uuid.uuid4()}/boq-items", **h(owner))
    assert missing.status_code == 404


def test_billed_boq_item_cannot_be_deleted(t: TenantFixture, owner: Member) -> None:
    client = party(owner).json()["id"]
    proj = project(owner, t, client).json()["id"]
    spare = boq(owner, proj, item_code="9.9").json()["id"]
    billed = boq(owner, proj).json()["id"]
    doc = _draft_document(t, proj, client)
    with tenant_context(t.tenant_id, t.user_id):
        DocumentLine.objects.create(
            document=doc,
            line_no=1,
            boq_item_id=billed,
            description="RCC",
            quantity=1,
            rate=100,
            taxable_value=100,
            line_total=100,
        )
    api = APIClient()
    assert api.delete(f"/api/v1/boq-items/{spare}", **h(owner)).status_code == 204
    assert problem(api.delete(f"/api/v1/boq-items/{billed}", **h(owner))) == (
        409,
        "boq_item_billed",
    )


# --- catalog --------------------------------------------------------------------------


def test_catalog_crud_and_used_items_are_archived_not_deleted(
    t: TenantFixture, owner: Member
) -> None:
    item = post(
        owner,
        "/api/v1/catalog-items",
        {
            "name": "OPC cement 53 grade",
            "unit": "bag",
            "sac_hsn": "2523",
            "default_rate": "380.00",
            "gst_rate": "28.00",
        },
    )
    assert item.status_code == 201, item.content
    url = f"/api/v1/catalog-items/{item.json()['id']}"
    assert patch(owner, url, {"default_rate": "395.00"}).json()["default_rate"] == "395.00"

    client = party(owner).json()["id"]
    doc = _draft_document(t, project(owner, t, client).json()["id"], client)
    with tenant_context(t.tenant_id, t.user_id):
        DocumentLine.objects.create(
            document=doc,
            line_no=1,
            catalog_item_id=item.json()["id"],
            description="Cement",
            quantity=1,
            rate=100,
            taxable_value=100,
            line_total=100,
        )
    assert problem(APIClient().delete(url, **h(owner))) == (409, "catalog_item_used")
    assert patch(owner, url, {"is_active": False}, version=2).json()["is_active"] is False
