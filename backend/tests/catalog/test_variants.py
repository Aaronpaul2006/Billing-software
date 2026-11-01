"""Catalog item variants (W.4): OPC 53 cement at 380.00, UltraTech +20.00, a
local brand -15.00; bills price the variant at item rate + delta."""

import uuid
from typing import Any

import pytest
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.documents.models import DocumentLine
from tests.documents.test_drafts import World
from tests.factories import add_member

pytestmark = pytest.mark.django_db


class Shop(World):
    def __init__(self) -> None:
        super().__init__()
        self.cement = self.item("OPC 53 cement", "380.00")
        self.ultratech = self.variant(self.cement, "Brand", "UltraTech", "20.00")
        self.local = self.variant(self.cement, "Brand", "Local", "-15.00")

    def post(self, path: str, body: dict[str, Any], member: Any = None) -> Any:
        return APIClient().post(
            f"/api/v1{path}",
            body,
            format="json",
            **self.h(member, IDEMPOTENCY_KEY=str(uuid.uuid4())),
        )

    def item(self, name: str, rate: str | None) -> dict[str, Any]:
        r = self.post(
            "/catalog-items",
            {
                "name": name,
                "unit": "bag",
                "sac_hsn": "2523",
                "default_rate": rate,
                "gst_rate": "28.00",
            },
        )
        assert r.status_code == 201, r.content
        return dict(r.json())

    def variant(
        self, item: dict[str, Any], attribute: str, value: str, delta: str
    ) -> dict[str, Any]:
        r = self.post(
            f"/catalog-items/{item['id']}/variants",
            {"attribute": attribute, "value": value, "rate_delta": delta},
        )
        assert r.status_code == 201, r.content
        return dict(r.json())

    def line(self, **over: Any) -> dict[str, Any]:
        return {"catalog_item_id": self.cement["id"], "quantity": "100", **over}


@pytest.fixture
def w() -> Shop:
    return Shop()


def test_a_variant_prices_the_line(w: Shop) -> None:
    r = w.create(project_id=None, lines=[w.line(catalog_variant_id=w.ultratech["id"])])
    assert r.status_code == 201, r.content
    line = r.json()["lines"][0]
    assert line["rate"] == "400.00"  # 380.00 + 20.00
    assert line["description"] == "OPC 53 cement — Brand: UltraTech"
    assert (line["unit"], line["sac_hsn"], line["gst_rate"]) == ("bag", "2523", "28.00")
    assert line["catalog_variant_id"] == w.ultratech["id"]
    assert r.json()["totals"]["subtotal"] == "40000.00"

    cheaper = w.create(project_id=None, lines=[w.line(catalog_variant_id=w.local["id"])])
    assert cheaper.json()["lines"][0]["rate"] == "365.00"  # 380.00 - 15.00
    typed = w.create(
        project_id=None, lines=[w.line(catalog_variant_id=w.ultratech["id"], rate="395.00")]
    )
    assert typed.json()["lines"][0]["rate"] == "395.00"  # what was typed wins


def test_lines_are_checked(w: Shop) -> None:
    steel = w.item("TMT bar", "62.00")
    for line, code in (
        (
            w.line(catalog_item_id=steel["id"], catalog_variant_id=w.ultratech["id"]),
            "variant_mismatch",
        ),
        (
            {
                "catalog_variant_id": w.ultratech["id"],
                "quantity": "1",
                "description": "x",
                "rate": "1",
            },
            "variant_without_item",
        ),
        (w.line(catalog_variant_id=str(uuid.uuid4())), "not_found"),
    ):
        r = w.create(project_id=None, lines=[line])
        assert r.status_code == 422, line
        assert (r.json()["errors"][0]["field"], r.json()["errors"][0]["code"]) == (
            "lines[0].catalog_variant_id",
            code,
        )
    cheap = w.item("Sand", "10.00")
    minus = w.variant(cheap, "Grade", "Waste", "-25.00")
    r = w.create(
        project_id=None, lines=[w.line(catalog_item_id=cheap["id"], catalog_variant_id=minus["id"])]
    )
    assert r.json()["errors"][0]["code"] == "negative_rate"


def test_the_database_keeps_a_variant_with_its_own_item(w: Shop) -> None:
    steel = w.item("TMT bar", "62.00")
    draft = w.create(project_id=None, lines=[w.line(catalog_variant_id=w.ultratech["id"])]).json()
    with (
        tenant_context(w.t.tenant_id, w.t.user_id),
        pytest.raises(IntegrityError),
        transaction.atomic(),
    ):
        DocumentLine.objects.filter(document_id=draft["id"]).update(catalog_item_id=steel["id"])


def test_variants_listed_edited_archived_and_deleted(w: Shop) -> None:
    item = APIClient().get(f"/api/v1/catalog-items/{w.cement['id']}", **w.h()).json()
    assert [(v["attribute"], v["value"], v["rate_delta"]) for v in item["variants"]] == [
        ("Brand", "Local", "-15.00"),
        ("Brand", "UltraTech", "20.00"),
    ]
    listed = APIClient().get("/api/v1/catalog-items", **w.h()).json()["results"]
    assert len(listed[0]["variants"]) == 2
    again = w.post(
        f"/catalog-items/{w.cement['id']}/variants", {"attribute": "Brand", "value": "UltraTech"}
    )
    assert (again.status_code, again.json()["code"]) == (409, "variant_exists")
    url = f"/api/v1/catalog-variants/{w.ultratech['id']}"
    r = APIClient().patch(url, {"rate_delta": "25.00"}, format="json", **w.h(IF_MATCH='"v1"'))
    assert (r.status_code, r.json()["rate_delta"]) == (200, "25.00")
    w.create(project_id=None, lines=[w.line(catalog_variant_id=w.ultratech["id"])])
    used = APIClient().delete(url, **w.h())
    assert (used.status_code, used.json()["code"]) == (409, "variant_used")
    r = APIClient().patch(url, {"is_active": False}, format="json", **w.h(IF_MATCH='"v2"'))
    assert r.json()["is_active"] is False
    assert (
        APIClient().delete(f"/api/v1/catalog-variants/{w.local['id']}", **w.h()).status_code == 204
    )


def test_roles(w: Shop) -> None:
    engineer = add_member(w.t, "SITE_ENGINEER")
    r = w.post(
        f"/catalog-items/{w.cement['id']}/variants",
        {"attribute": "Brand", "value": "ACC"},
        engineer,
    )
    assert r.status_code == 403
    r = APIClient().get(f"/api/v1/catalog-items/{w.cement['id']}/variants", **w.h(engineer))
    assert r.status_code == 200
    assert len(r.json()["results"]) == 2
    assert (
        APIClient().get(f"/api/v1/catalog-items/{uuid.uuid4()}/variants", **w.h()).status_code
        == 404
    )
