"""SEZ supplies, exports, LUT and reverse charge, end to end through the API.

IGST Act s.7(5)(b) (SEZ supplies are inter-State), s.12(3) / s.13(4) (works on
immovable property: the site decides), s.16 (zero-rated: IGST or LUT);
CGST Rules r.46 (the declarations printed on such invoices).
"""

import json
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.documents.models import Document
from apps.documents.pdf.render import build_context, render_html
from apps.exports.gstr1 import build_gstr1
from apps.parties.models import Party
from apps.projects.models import Project
from apps.tenants.models import GstRegistration
from tests.factories import gstin

from .test_drafts import World
from .test_lifecycle import act, problem, series

pytestmark = pytest.mark.django_db

ARN = "AD320426001234X"


class Gst(World):
    def __init__(self) -> None:
        super().__init__()
        with tenant_context(self.t.tenant_id, self.t.user_id):
            self.sez = Party.objects.create(
                display_name="Infopark SEZ Unit",
                gst_treatment="SEZ",
                gstin=gstin("32", pan="AAACI5555I"),
                pan="AAACI5555I",
                state_code="32",
                created_by_id=self.t.user_id,
            )
            self.overseas = Party.objects.create(
                display_name="Gulf Holdings LLC",
                gst_treatment="OVERSEAS",
                created_by_id=self.t.user_id,
            )
            self.consumer = Party.objects.create(
                display_name="Mary Joseph",
                gst_treatment="CONSUMER",
                state_code="32",
                created_by_id=self.t.user_id,
            )
            self.overseas_site = Project.objects.create(
                code="VILLA-NRI",
                name="Villa for an overseas client",
                client_party=self.overseas,
                gst_registration_id=self.t.registration_id,
                site_state_code="32",
                created_by_id=self.t.user_id,
            )

    def draft(self, party: Party, **body: Any) -> dict[str, Any]:
        response = self.create(party_id=str(party.pk), project_id=None, **body)
        assert response.status_code == 201, response.content
        result: dict[str, Any] = response.json()
        return result

    def set_lut(self, arn: str | None, fy: int | None) -> Any:
        url = f"/api/v1/gst-registrations/{self.t.registration_id}"
        version = APIClient().get(url, **self.h()).json()["version"]
        return APIClient().patch(
            url,
            {"lut_arn": arn, "lut_fy_start_year": fy},
            format="json",
            **self.h(IF_MATCH=f'"v{version}"'),
        )


@pytest.fixture
def g() -> Gst:
    world = Gst()
    series(world)
    series(world, "CREDIT_NOTE", "CN/")
    return world


def totals(doc: dict[str, Any]) -> tuple[str, str, str, str]:
    t = doc["totals"]
    return t["cgst"], t["sgst"], t["igst"], t["grand_total"]


def test_sez_in_the_same_state_pays_igst(g: Gst) -> None:
    doc = g.draft(g.sez)
    assert (doc["supply_category"], doc["place_of_supply"], doc["supply_type"]) == (
        "SEZ",
        "32",
        "INTER_STATE",
    )
    assert doc["lut"] is False  # no LUT on the registration yet
    assert totals(doc) == ("0.00", "0.00", "52020.00", "341020.00")
    issued = act(g, doc, "issue")
    assert issued.status_code == 200, issued.content  # the issue guard accepts it
    with tenant_context(g.t.tenant_id, g.t.user_id):
        context = build_context(Document.objects.get(pk=doc["id"]))
    assert context["declaration"].startswith("SUPPLY TO SEZ UNIT OR SEZ DEVELOPER")
    assert context["declaration"].endswith("ON PAYMENT OF INTEGRATED TAX")


def test_zero_rated_under_the_lut(g: Gst) -> None:
    assert g.set_lut(ARN.lower(), 2026).status_code == 200  # stored upper-case
    doc = g.draft(g.sez)
    assert doc["lut"] is True
    assert totals(doc) == ("0.00", "0.00", "0.00", "289000.00")
    assert doc["lines"][0]["gst_rate"] == "18.00"  # the rate stays for the return
    issued = act(g, doc, "issue")
    assert issued.status_code == 200, issued.content
    with tenant_context(g.t.tenant_id, g.t.user_id):
        stored = Document.objects.get(pk=doc["id"])
        context = build_context(stored)
    assert stored.supplier_snapshot is not None
    assert stored.supplier_snapshot["lut_arn"] == ARN
    assert "WITHOUT PAYMENT OF INTEGRATED TAX (LUT ARN AD320426001234X)" in context["declaration"]
    with tenant_context(g.t.tenant_id, g.t.user_id):
        html = render_html(stored)
    assert "LUT ARN AD320426001234X" in html
    assert "Place of supply: 32 - Kerala" in html

    # The user may still choose to pay IGST.
    paid = g.draft(g.sez, lut=False)
    assert (paid["lut"], totals(paid)[2]) == (False, "52020.00")


def test_lut_must_cover_the_financial_year(g: Gst) -> None:
    g.set_lut(ARN, 2026)
    next_year = g.draft(g.sez, doc_date="2027-04-05")
    assert next_year["lut"] is False  # LUT 2026-27 does not cover 2027-28
    refused = g.create(party_id=str(g.sez.pk), project_id=None, doc_date="2027-04-05", lut=True)
    assert problem(refused) == (422, "no_lut")

    # A draft under the LUT whose LUT is then removed cannot be issued.
    doc = g.draft(g.sez)
    assert doc["lut"] is True
    g.set_lut(None, None)
    assert problem(act(g, doc, "issue")) == (422, "no_lut")


def test_exports_and_overseas_clients_with_a_site_in_india(g: Gst) -> None:
    g.set_lut(ARN, 2026)
    export = g.draft(g.overseas)
    assert (export["supply_category"], export["place_of_supply"], export["lut"]) == (
        "EXPORT",
        "96",
        True,
    )
    assert totals(export) == ("0.00", "0.00", "0.00", "289000.00")
    with_igst = g.draft(g.overseas, lut=False)
    assert totals(with_igst)[2] == "52020.00"
    assert act(g, with_igst, "issue").status_code == 200

    # Works on a site in Kerala: the place of supply is the site, a domestic supply.
    site = g.create(party_id=str(g.overseas.pk), project_id=str(g.overseas_site.pk)).json()
    assert (site["supply_category"], site["place_of_supply"], site["supply_type"]) == (
        "REGULAR",
        "32",
        "INTRA_STATE",
    )
    assert totals(site)[:2] == ("26010.00", "26010.00")
    assert site["lut"] is False


def test_reverse_charge(g: Gst) -> None:
    doc = g.create(reverse_charge=True).json()  # registered client, Kerala site
    assert doc["reverse_charge"] is True
    assert totals(doc) == ("26010.00", "26010.00", "0.00", "289000.00")  # tax shown, not added
    # project deductions: 5 % retention, 1 % TDS on 2,89,000
    assert doc["totals"]["net_receivable"] == "271660.00"
    assert act(g, doc, "issue").status_code == 200
    with tenant_context(g.t.tenant_id, g.t.user_id):
        html = render_html(Document.objects.get(pk=doc["id"]))
    assert "CGST (payable by the recipient)" in html
    assert "payable by the recipient under reverse charge" in html

    summary = APIClient().get("/api/v1/reports/gst-summary?period=2026-10", **g.h()).json()
    assert [r["supply"] for r in summary["results"]] == ["B2B_REVERSE_CHARGE"]
    month = APIClient().get("/api/v1/reports/summary?from=2026-10-01&to=2026-10-31", **g.h()).json()
    assert month["current"]["tax"] == "0.00"  # the recipient's tax, not ours

    for party in (g.consumer, g.sez):  # unregistered client; SEZ supply
        refused = g.create(party_id=str(party.pk), project_id=None, reverse_charge=True)
        assert problem(refused) == (422, "reverse_charge_not_allowed")
    for doc_type in ("QUOTATION", "PROFORMA", "BILL_OF_SUPPLY"):  # not tax invoices
        refused = g.create(doc_type=doc_type, reverse_charge=True)
        assert problem(refused) == (422, "reverse_charge_not_allowed"), doc_type


def test_a_credit_note_follows_its_invoice(g: Gst) -> None:
    g.set_lut(ARN, 2026)
    invoice = act(g, g.draft(g.sez), "issue").json()
    note = act(g, invoice, "credit-notes", body={"doc_date": "2026-10-30"}).json()
    assert (note["supply_category"], note["lut"], totals(note)[2]) == ("SEZ", True, "0.00")


def test_gstr1_uses_the_category_and_the_lut(g: Gst) -> None:
    g.set_lut(ARN, 2026)
    act(g, g.draft(g.sez), "issue")  # SEZ under LUT
    act(g, g.draft(g.sez, lut=False), "issue")  # SEZ with IGST
    act(g, g.draft(g.overseas), "issue")  # export under LUT
    act(g, g.create(reverse_charge=True).json(), "issue")  # reverse charge
    with tenant_context(g.t.tenant_id, g.t.user_id):
        body, _, _, warnings = build_gstr1(
            g.t.tenant_id, {"gst_registration_id": str(g.t.registration_id), "period": "2026-10"}
        )
    data = json.loads(body)
    sez = next(b for b in data["b2b"] if b["ctin"] == g.sez.gstin)
    assert sorted(inv["inv_typ"] for inv in sez["inv"]) == ["SEWOP", "SEWP"]
    sewop = next(inv for inv in sez["inv"] if inv["inv_typ"] == "SEWOP")
    assert sewop["itms"][0]["itm_det"] == {"txval": 289000.0, "rt": 18, "iamt": 0.0, "csamt": 0.0}
    assert data["exp"] == [
        {
            "exp_typ": "WOPAY",
            "inv": [
                {
                    "inum": data["exp"][0]["inv"][0]["inum"],
                    "idt": "19-10-2026",
                    "val": 289000.0,
                    "itms": [{"txval": 289000.0, "rt": 18, "iamt": 0.0, "csamt": 0.0}],
                }
            ],
        }
    ]
    rcm = next(b for b in data["b2b"] if b["ctin"] == g.client.gstin)
    assert rcm["inv"][0]["rchrg"] == "Y"
    assert not any("taxed here by place of supply" in w for w in warnings)


def test_registration_lut_rules(g: Gst) -> None:
    assert problem(g.set_lut(ARN, None)) == (422, "required")
    assert problem(g.set_lut("SHORT", 2026)) == (422, "invalid")
    with tenant_context(g.t.tenant_id, g.t.user_id):
        GstRegistration.objects.filter(pk=g.t.registration_id).update(
            registration_type="COMPOSITION"
        )
    assert problem(g.set_lut(ARN, 2026)) == (422, "not_allowed")


def test_the_database_keeps_the_rules(g: Gst) -> None:
    """Even a buggy service cannot store a zero-rated document with tax, or
    reverse-charge tax inside the total."""
    from django.db import IntegrityError, transaction

    doc = g.draft(g.sez)
    with tenant_context(g.t.tenant_id, g.t.user_id):
        for change in (
            {"lut": True},  # IGST charged on a document marked LUT
            {"supply_type": "INTRA_STATE"},  # SEZ supply as intra-State
            {"reverse_charge": True},  # reverse charge on an SEZ supply
        ):
            with pytest.raises(IntegrityError), transaction.atomic():
                Document.objects.filter(pk=doc["id"]).update(**change)
