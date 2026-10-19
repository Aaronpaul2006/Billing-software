"""Draft documents: server-computed totals, editing, deleting, preview (Phase 1.5)."""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.models import CatalogItem
from apps.core.tenancy import tenant_context
from apps.documents.models import Document, DocumentLine
from apps.parties.models import Party
from apps.projects.models import BoqItem, Project
from apps.tenants.models import DocumentSeries, GstRegistration
from tests.factories import Member, TenantFixture, add_member, gstin, make_tenant, owner_member

pytestmark = pytest.mark.django_db

RCC = {
    "description": "RCC M25 for slab, 2nd floor",
    "sac_hsn": "9954",
    "unit": "cum",
    "quantity": "42.500",
    "rate": "6800.00",
    "gst_rate": "18.00",
}


class World:
    def __init__(self) -> None:
        self.t: TenantFixture = make_tenant("Nair Constructions", state_code="32")
        self.owner: Member = owner_member(self.t)
        with tenant_context(self.t.tenant_id, self.t.user_id):
            self.client = Party.objects.create(
                display_name="Skyline Developers",
                gst_treatment="REGISTERED",
                gstin=gstin("32", pan="AAACS4321K"),
                pan="AAACS4321K",
                state_code="32",
                created_by_id=self.t.user_id,
            )
            self.project = self.make_project("VILLA-1", "32")

    def make_project(self, code: str, site_state: str, **kw: Any) -> Project:
        with tenant_context(self.t.tenant_id, self.t.user_id):
            project: Project = Project.objects.create(
                code=code,
                name=code,
                client_party=self.client,
                gst_registration_id=self.t.registration_id,
                site_state_code=site_state,
                retention_pct=Decimal("5"),
                income_tax_tds_pct=Decimal("1"),
                created_by_id=self.t.user_id,
                **kw,
            )
        return project

    def h(self, member: Member | None = None, **extra: str) -> dict[str, Any]:
        m = member or self.owner
        return {
            "HTTP_AUTHORIZATION": f"Bearer {m.access_token}",
            **{f"HTTP_{k}": v for k, v in extra.items()},
        }

    def create(self, member: Member | None = None, key: str | None = None, **body: Any) -> Any:
        payload = {
            "doc_type": "TAX_INVOICE",
            "party_id": str(self.client.pk),
            "project_id": str(self.project.pk),
            "doc_date": "2026-10-19",
            "lines": [RCC],
            **body,
        }
        return APIClient().post(
            "/api/v1/documents",
            payload,
            format="json",
            **self.h(member, IDEMPOTENCY_KEY=key or str(uuid.uuid4())),
        )


@pytest.fixture
def w() -> World:
    return World()


def problem(r: Any) -> tuple[int, str]:
    b = r.json()
    return r.status_code, (b["errors"][0]["code"] if b["code"] == "validation_error" else b["code"])


# --- creating ---------------------------------------------------------------------------


def test_create_draft_matches_the_api_design_example(w: World) -> None:
    r = w.create(due_date="2026-11-18", notes="RA Bill 3 for work up to 15 Oct")
    assert r.status_code == 201, r.content
    body = r.json()
    assert (body["status"], body["doc_number"], body["version"]) == ("DRAFT", None, 1)
    assert (body["place_of_supply"], body["supply_type"]) == ("32", "INTRA_STATE")
    assert body["totals"] == {
        "subtotal": "289000.00",
        "cgst": "26010.00",
        "sgst": "26010.00",
        "igst": "0.00",
        "cess": "0.00",
        "round_off": "0.00",
        "grand_total": "341020.00",
        "retention": "14450.00",
        "income_tax_tds": "2890.00",
        "gst_tds": "0.00",
        "advance_recovery": "0.00",
        "net_receivable": "323680.00",
        "amount_settled": "0.00",
        "outstanding": "323680.00",
    }
    [line] = body["lines"]
    assert (line["taxable_value"], line["cgst_amount"], line["line_total"]) == (
        "289000.00",
        "26010.00",
        "341020.00",
    )
    assert r["ETag"] == '"v1"'


def test_create_is_idempotent(w: World) -> None:
    key = str(uuid.uuid4())
    first, retry = w.create(key=key), w.create(key=key)
    assert retry["Idempotent-Replayed"] == "true"
    assert first.json()["id"] == retry.json()["id"]
    with tenant_context(w.t.tenant_id, w.t.user_id):
        assert Document.objects.count() == 1


def test_client_cannot_set_tax_amounts(w: World) -> None:
    r = w.create(
        supply_type="INTER_STATE",
        place_of_supply="29",
        lines=[{**RCC, "cgst_amount": "0.00", "line_total": "1.00"}],
    )
    body = r.json()
    assert (body["supply_type"], body["totals"]["cgst"]) == ("INTRA_STATE", "26010.00")


def test_site_in_another_state_gets_igst(w: World) -> None:
    site_29 = w.make_project("BLR-1", "29")
    body = w.create(project_id=str(site_29.pk)).json()
    assert (body["place_of_supply"], body["supply_type"]) == ("29", "INTER_STATE")
    assert (body["totals"]["igst"], body["totals"]["cgst"]) == ("52020.00", "0.00")


def test_without_a_project_the_partys_state_is_the_place_of_supply(w: World) -> None:
    with tenant_context(w.t.tenant_id, w.t.user_id):
        Party.objects.filter(pk=w.client.pk).update(
            gstin=gstin("29", pan="AAACS4321K"), state_code="29"
        )
    body = w.create(project_id=None).json()
    assert (body["place_of_supply"], body["supply_type"]) == ("29", "INTER_STATE")
    assert body["totals"]["retention"] == "0.00"  # deductions come from projects


def test_advance_recovery_is_capped_at_the_outstanding_advance(w: World) -> None:
    project = w.make_project(
        "ADV-1", "32", mobilisation_advance=Decimal("20000"), advance_recovery_pct=Decimal("10")
    )
    body = w.create(project_id=str(project.pk)).json()
    assert body["totals"]["advance_recovery"] == "20000.00"  # 10 % would be 28900


def test_lines_fill_from_catalog_items(w: World) -> None:
    with tenant_context(w.t.tenant_id, w.t.user_id):
        item = CatalogItem.objects.create(
            name="OPC cement 53 grade",
            unit="bag",
            sac_hsn="2523",
            default_rate=Decimal("380"),
            gst_rate=Decimal("28"),
        )
    r = w.create(
        project_id=None,
        doc_type="QUOTATION",
        lines=[{"catalog_item_id": str(item.pk), "quantity": "100"}],
    )
    assert r.status_code == 201, r.content
    line = r.json()["lines"][0]
    assert (line["description"], line["unit"], line["rate"], line["gst_rate"]) == (
        "OPC cement 53 grade",
        "bag",
        "380.00",
        "28.00",
    )
    assert r.json()["totals"]["grand_total"] == "48640.00"  # 38000 + 28 %


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"doc_type": "CREDIT_NOTE"}, "invalid_choice"),
        ({"due_date": "2026-10-01"}, "invalid_dates"),
        ({"valid_until": "2026-12-31"}, "not_allowed"),
        ({"lines": [{**RCC, "rate": 6800}]}, "not_a_string"),
        ({"lines": [{**RCC, "gst_rate": "51"}]}, "max_value"),
        ({"lines": [{**RCC, "description": None, "quantity": "1"}]}, "null"),
        ({"lines": [{"quantity": "1", "rate": "10"}]}, "required"),
        ({"party_id": str(uuid.uuid4())}, "not_found"),
    ],
)
def test_create_validation(w: World, body: dict[str, Any], code: str) -> None:
    assert problem(w.create(**body)) == (422, code)


def test_reference_rules(w: World) -> None:
    with tenant_context(w.t.tenant_id, w.t.user_id):
        vendor = Party.objects.create(
            display_name="Cement Co",
            gst_treatment="UNREGISTERED",
            is_customer=False,
            is_vendor=True,
            created_by_id=w.t.user_id,
        )
        other = Party.objects.create(
            display_name="Other", gst_treatment="UNREGISTERED", created_by_id=w.t.user_id
        )
        composition = GstRegistration.objects.create(
            registration_type="COMPOSITION",
            gstin=gstin("32", pan="AAACA1234A", entity="5"),
            state_code="32",
            legal_name="x",
            address={},
        )
        boq_elsewhere = BoqItem.objects.create(
            project=w.make_project("P2", "32"),
            item_code="1",
            description="x",
            unit="nos",
            contract_qty=1,
            rate=1,
        )
    assert problem(w.create(party_id=str(vendor.pk), project_id=None)) == (422, "not_a_customer")
    assert problem(w.create(party_id=str(other.pk))) == (422, "party_mismatch")
    assert problem(w.create(gst_registration_id=str(composition.pk))) == (
        422,
        "registration_mismatch",
    )
    assert problem(w.create(gst_registration_id=str(composition.pk), project_id=None)) == (
        422,
        "doc_type_not_allowed",
    )
    assert (
        w.create(
            gst_registration_id=str(composition.pk), project_id=None, doc_type="BILL_OF_SUPPLY"
        ).json()["totals"]["cgst"]
        == "0.00"
    )
    assert problem(w.create(lines=[{**RCC, "boq_item_id": str(boq_elsewhere.pk)}])) == (
        422,
        "boq_item_mismatch",
    )


def test_roles(w: World) -> None:
    assert problem(w.create(member=add_member(w.t, "VIEWER"))) == (403, "permission_denied")
    assert w.create(member=add_member(w.t, "SITE_ENGINEER")).status_code == 201


# --- editing, deleting -------------------------------------------------------------------


def test_patch_replaces_lines_and_recomputes(w: World) -> None:
    doc = w.create().json()
    url, api = f"/api/v1/documents/{doc['id']}", APIClient()
    assert problem(api.patch(url, {"lines": [RCC]}, format="json", **w.h())) == (
        428,
        "if_match_required",
    )

    more = {**RCC, "description": "Brickwork", "quantity": "10", "rate": "1000"}
    r = api.patch(url, {"lines": [RCC, more]}, format="json", **w.h(IF_MATCH='"v1"'))
    assert r.status_code == 200, r.content
    assert r["ETag"] == '"v2"'
    assert [ln["line_no"] for ln in r.json()["lines"]] == [1, 2]
    assert r.json()["totals"]["subtotal"] == "299000.00"

    rounded = api.patch(
        url,
        {"round_to_rupee": True, "lines": [{**RCC, "rate": "6800.33"}]},
        format="json",
        **w.h(IF_MATCH='"v2"'),
    )
    totals = rounded.json()["totals"]
    assert Decimal(totals["round_off"]) != 0
    assert totals["grand_total"].endswith(".00")

    keep = api.patch(url, {"notes": "only notes"}, format="json", **w.h(IF_MATCH='"v3"'))
    assert keep.json()["totals"] == totals  # lines and rounding kept

    stale = api.patch(url, {"notes": "late"}, format="json", **w.h(IF_MATCH='"v1"'))
    assert problem(stale) == (412, "stale_version")
    assert stale.json()["current"]["version"] == 4


def _issue(w: World, doc_id: str) -> None:
    with tenant_context(w.t.tenant_id, w.t.user_id):
        series = DocumentSeries.objects.create(
            gst_registration_id=w.t.registration_id,
            doc_type="TAX_INVOICE",
            fy_start_year=2026,
            prefix="T/",
        )
        with connection.cursor() as c:
            c.execute(
                "UPDATE documents SET status = 'ISSUED', series_id = %s, doc_number = 'T/0001',"
                " issued_at = %s, issued_by = %s, supplier_snapshot = '{}', party_snapshot = '{}'"
                " WHERE id = %s",
                [series.pk, timezone.now(), w.t.user_id, doc_id],
            )


def test_issued_documents_cannot_be_edited_or_deleted(w: World) -> None:
    doc = w.create().json()
    _issue(w, doc["id"])
    url, api = f"/api/v1/documents/{doc['id']}", APIClient()
    assert problem(api.patch(url, {"notes": "x"}, format="json", **w.h(IF_MATCH='"v1"'))) == (
        409,
        "document_not_draft",
    )
    assert problem(api.delete(url, **w.h())) == (409, "document_not_draft")


def test_delete_a_draft(w: World) -> None:
    doc = w.create().json()
    assert APIClient().delete(f"/api/v1/documents/{doc['id']}", **w.h()).status_code == 204
    with tenant_context(w.t.tenant_id, w.t.user_id):
        assert not Document.objects.filter(pk=doc["id"]).exists()
        assert not DocumentLine.objects.filter(document_id=doc["id"]).exists()


# --- preview, list ------------------------------------------------------------------------


def test_preview_totals_saves_nothing(w: World) -> None:
    payload = {
        "doc_type": "TAX_INVOICE",
        "party_id": str(w.client.pk),
        "project_id": str(w.project.pk),
        "doc_date": "2026-10-19",
        "lines": [RCC],
    }
    r = APIClient().post("/api/v1/documents:preview-totals", payload, format="json", **w.h())
    assert r.status_code == 200, r.content
    assert r.json()["totals"]["net_receivable"] == "323680.00"
    assert r.json()["lines"][0]["cgst_amount"] == "26010.00"
    with tenant_context(w.t.tenant_id, w.t.user_id):
        assert Document.objects.count() == 0


def test_list_filters(w: World) -> None:
    w.create()
    w.create(doc_type="QUOTATION", valid_until="2026-11-30")
    w.create(doc_type="PROFORMA")
    api = APIClient()

    def types(**q: str) -> list[str]:
        return sorted(
            d["doc_type"] for d in api.get("/api/v1/documents", q, **w.h()).json()["results"]
        )

    assert types(doc_type="TAX_INVOICE,QUOTATION") == ["QUOTATION", "TAX_INVOICE"]
    assert types(book="GST") == ["TAX_INVOICE"]
    assert types(book="NON_GST") == ["PROFORMA", "QUOTATION"]
    assert types(payment_state="UNPAID", status="DRAFT") == ["PROFORMA", "QUOTATION", "TAX_INVOICE"]
    assert types(doc_date_from="2026-10-20") == []
