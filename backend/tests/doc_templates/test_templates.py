"""Quotation / bill templates (W.3)."""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.projects.models import BoqItem
from tests.documents.test_drafts import RCC
from tests.factories import add_member
from tests.payments.test_payments import Money

pytestmark = pytest.mark.django_db

PAINT = {
    "description": "Interior emulsion, 2 coats",
    "sac_hsn": "995473",
    "unit": "sqm",
    "quantity": "420",
    "rate": "65.50",
    "gst_rate": "18.00",
}


class Templates(Money):
    def post(self, path: str, body: dict[str, Any], member: Any = None) -> Any:
        return APIClient().post(
            f"/api/v1{path}",
            body,
            format="json",
            **self.h(member, IDEMPOTENCY_KEY=str(uuid.uuid4())),
        )

    def quote(self) -> dict[str, Any]:
        r = self.create(
            doc_type="QUOTATION",
            project_id=None,
            doc_date="2026-10-20",
            valid_until="2026-11-19",
            lines=[RCC, PAINT],
            notes="Prices include material and labour.",
            terms="50 % advance, balance on completion.",
        )
        assert r.status_code == 201, r.content
        return dict(r.json())

    def template(self, **over: Any) -> dict[str, Any]:
        body = {
            "name": "2BHK interior",
            "doc_type": "QUOTATION",
            "valid_days": 15,
            "lines": [PAINT],
        }
        r = self.post("/document-templates", {**body, **over})
        assert r.status_code == 201, r.content
        return dict(r.json())


@pytest.fixture
def w() -> Templates:
    return Templates()


def test_a_quote_saved_as_a_template_starts_the_next_quote(w: Templates) -> None:
    quote = w.quote()
    r = w.post(f"/documents/{quote['id']}/save-as-template", {"name": "2BHK interior"})
    assert r.status_code == 201, r.content
    t = r.json()
    assert (t["doc_type"], t["valid_days"]) == ("QUOTATION", 30)  # 20 Oct to 19 Nov
    assert t["notes"] == "Prices include material and labour."
    assert t["lines"][1] == {
        "description": "Interior emulsion, 2 coats",
        "sac_hsn": "995473",
        "unit": "sqm",
        "quantity": "420.000",
        "rate": "65.50",
        "discount_amount": "0.00",
        "discount_pct": None,
        "gst_rate": "18.00",
    }

    r = w.post(
        f"/document-templates/{t['id']}/use",
        {"party_id": str(w.client.pk), "project_id": str(w.project.pk), "doc_date": "2026-11-01"},
    )
    assert r.status_code == 201, r.content
    draft = r.json()
    assert (draft["doc_type"], draft["status"], draft["valid_until"]) == (
        "QUOTATION",
        "DRAFT",
        "2026-12-01",
    )
    assert draft["project_id"] == str(w.project.pk)
    assert draft["terms"] == "50 % advance, balance on completion."
    assert [ln["description"] for ln in draft["lines"]] == [
        RCC["description"],
        PAINT["description"],
    ]
    # Worked out by the draft rules: 289000 + 27510 (420 x 65.50), CGST + SGST at 9 % each.
    assert draft["totals"]["subtotal"] == "316510.00"
    assert draft["totals"]["cgst"] == "28485.90"
    assert draft["place_of_supply"] == "32"


def test_boq_lines_become_plain_lines(w: Templates) -> None:
    with tenant_context(w.t.tenant_id, w.t.user_id):
        item = BoqItem.objects.create(
            project=w.project,
            item_code="2.1",
            description="RCC M25",
            unit="cum",
            contract_qty=Decimal("100"),
            rate=Decimal("6800"),
            gst_rate=Decimal("18"),
        )
    r = w.create(lines=[{"boq_item_id": str(item.pk), "quantity": "10"}])
    assert r.status_code == 201, r.content
    r = w.post(f"/documents/{r.json()['id']}/save-as-template", {"name": "Slab"})
    assert r.status_code == 201, r.content
    line = r.json()["lines"][0]
    assert (line["description"], line["rate"], line["unit"]) == ("RCC M25", "6800.00", "cum")
    assert "boq_item_id" not in line
    assert r.json()["valid_days"] is None  # an invoice has no validity


def test_create_rename_and_delete(w: Templates) -> None:
    t = w.template()
    again = w.post("/document-templates", {"name": "2BHK interior", "lines": [PAINT]})
    assert (again.status_code, again.json()["code"]) == (409, "template_name_taken")
    listed = APIClient().get("/api/v1/document-templates", **w.h()).json()["results"]
    assert [x["name"] for x in listed] == ["2BHK interior"]
    url = f"/api/v1/document-templates/{t['id']}"
    r = APIClient().patch(
        url, {"name": "2BHK interior (2026)"}, format="json", **w.h(IF_MATCH='"v1"')
    )
    assert (r.status_code, r.json()["name"], r.json()["version"]) == (
        200,
        "2BHK interior (2026)",
        2,
    )
    # Turned into an invoice template: the quotation validity goes.
    r = APIClient().patch(url, {"doc_type": "TAX_INVOICE"}, format="json", **w.h(IF_MATCH='"v2"'))
    assert (r.status_code, r.json()["valid_days"]) == (200, None)
    assert APIClient().delete(url, **w.h()).status_code == 204
    assert APIClient().get(url, **w.h()).status_code == 404


def test_rules(w: Templates) -> None:
    r = w.post(
        "/document-templates",
        {"name": "Bill", "doc_type": "TAX_INVOICE", "valid_days": 10, "lines": [PAINT]},
    )
    assert (r.status_code, r.json()["errors"][0]["field"]) == (422, "valid_days")
    r = w.post("/document-templates", {"name": "Empty", "lines": []})
    assert (r.status_code, r.json()["errors"][0]["field"]) == (422, "lines")
    r = w.post("/document-templates", {"name": "Bad", "lines": [{**PAINT, "rate": 65.5}]})
    assert r.status_code == 422  # money is a string, never a JSON number
    invoice = w.invoice()
    with tenant_context(w.t.tenant_id, w.t.user_id):
        from apps.tenants.models import DocumentSeries

        DocumentSeries.objects.create(
            gst_registration_id=w.t.registration_id,
            doc_type="CREDIT_NOTE",
            fy_start_year=2026,
            prefix="CN/",
        )
    note = w.post(
        f"/documents/{invoice['id']}/credit-notes",
        {"doc_date": "2026-10-30", "lines": [{**RCC, "quantity": "1"}]},
    ).json()
    r = w.post(f"/documents/{note['id']}/save-as-template", {"name": "Note"})
    assert (r.status_code, r.json()["code"]) == (409, "not_templatable")
    t = w.template()
    r = w.post(f"/document-templates/{t['id']}/use", {"party_id": str(uuid.uuid4())})
    assert r.status_code == 422  # an unknown client: the draft rules answer


def test_roles(w: Templates) -> None:
    t = w.template()
    engineer = add_member(w.t, "SITE_ENGINEER")
    assert (
        w.post("/document-templates", {"name": "X", "lines": [PAINT]}, engineer).status_code == 403
    )
    r = w.post(f"/document-templates/{t['id']}/use", {"party_id": str(w.client.pk)}, engineer)
    assert r.status_code == 201, r.content  # site engineers may start drafts
    viewer = add_member(w.t, "VIEWER")
    assert APIClient().get("/api/v1/document-templates", **w.h(viewer)).status_code == 200
    r = w.post(f"/document-templates/{t['id']}/use", {"party_id": str(w.client.pk)}, viewer)
    assert r.status_code == 403
