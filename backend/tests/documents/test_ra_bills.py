"""RA (running account) bills against the BOQ (Phase 3.2).

Project VILLA-1 BOQ:
  2.1  RCC M25           100 cum  @ 6800  (contract)
  3.1  Brickwork         500 sqm  @  900  (contract)
  V1   Extra parapet      10 rmt  @ 1000  (variation: may go past 10)
"""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.documents.models import Document
from apps.documents.pdf.render import build_context, render_html
from apps.projects.models import BoqItem

from .test_drafts import World
from .test_lifecycle import act, problem, series

pytestmark = pytest.mark.django_db


class Ra(World):
    def __init__(self) -> None:
        super().__init__()
        self.series = series(self)
        with tenant_context(self.t.tenant_id, self.t.user_id):
            self.rcc, self.brick, self.extra = (
                BoqItem.objects.create(
                    project=self.project,
                    item_code=code,
                    description=desc,
                    unit=unit,
                    contract_qty=Decimal(qty),
                    rate=Decimal(rate),
                    gst_rate=Decimal("18"),
                    is_variation=variation,
                    sort_order=n,
                )
                for n, (code, desc, unit, qty, rate, variation) in enumerate(
                    [
                        ("2.1", "RCC M25", "cum", "100", "6800", False),
                        ("3.1", "Brickwork", "sqm", "500", "900", False),
                        ("V1", "Extra parapet", "rmt", "10", "1000", True),
                    ],
                    start=1,
                )
            )

    def bill(self, *lines: tuple[BoqItem, str], ra: bool = True, **body: Any) -> Any:
        return self.create(
            is_ra_bill=ra,
            lines=[{"boq_item_id": str(item.pk), "quantity": qty} for item, qty in lines],
            **body,
        )

    def issued(self, *lines: tuple[BoqItem, str], ra: bool = True, **body: Any) -> Any:
        draft = self.bill(*lines, ra=ra, **body)
        assert draft.status_code == 201, draft.content
        r = act(self, draft.json(), "issue")
        assert r.status_code == 200, r.content
        return r.json()


@pytest.fixture
def w() -> Ra:
    return Ra()


def quantities(doc: dict[str, Any]) -> list[tuple[str | None, str, str | None]]:
    return [
        (ln["prev_cumulative_qty"], ln["quantity"], ln["up_to_date_qty"]) for ln in doc["lines"]
    ]


def test_previous_this_bill_and_up_to_date(w: Ra) -> None:
    first = w.issued((w.rcc, "42.500"), (w.brick, "200"))
    assert (first["is_ra_bill"], first["ra_sequence"], first["doc_number"]) == (
        True,
        1,
        "INV/0001",
    )
    assert quantities(first) == [("0.000", "42.500", "42.500"), ("0.000", "200.000", "200.000")]
    assert first["lines"][0]["rate"] == "6800.00"  # from the BOQ
    assert first["totals"]["subtotal"] == "469000.00"  # 289000 + 180000

    second = w.bill((w.brick, "150"), (w.rcc, "30"))
    assert second.status_code == 201, second.content
    assert second.json()["ra_sequence"] == 2
    assert quantities(second.json()) == [
        ("200.000", "150.000", "350.000"),
        ("42.500", "30.000", "72.500"),
    ]
    plain = w.issued((w.rcc, "1"), ra=False)  # a plain invoice also bills the item
    assert (
        plain["is_ra_bill"],
        plain["ra_sequence"],
        plain["lines"][0]["prev_cumulative_qty"],
    ) == (
        False,
        None,
        None,
    )
    issued = act(w, second.json(), "issue").json()  # the snapshot is retaken at issue
    assert quantities(issued) == [("200.000", "150.000", "350.000"), ("43.500", "30.000", "73.500")]
    listed = APIClient().get("/api/v1/documents", {"is_ra_bill": "true"}, **w.h()).json()
    assert sorted(d["ra_sequence"] for d in listed["results"]) == [1, 2]


def test_billing_past_the_contract_quantity(w: Ra) -> None:
    w.issued((w.rcc, "42.500"))
    r = w.bill((w.brick, "10"), (w.rcc, "57.501"))
    assert problem(r) == (422, "exceeds_boq_quantity")
    assert r.json()["errors"][0]["field"] == "lines[1].quantity"
    assert "contract quantity 100.000 cum, billed so far 42.500" in r.json()["errors"][0]["message"]
    assert problem(w.bill((w.rcc, "60"), ra=False)) == (422, "exceeds_boq_quantity")
    assert w.bill((w.rcc, "57.500")).status_code == 201  # exactly the contract quantity
    variation = w.issued((w.extra, "15"), ra=False)  # variations may go past
    assert variation["lines"][0]["quantity"] == "15.000"


def test_issue_rechecks_against_bills_issued_meanwhile(w: Ra) -> None:
    w.issued((w.rcc, "42.500"))
    draft = w.bill((w.rcc, "50"))  # 92.5 of 100: fine now
    assert draft.status_code == 201
    w.issued((w.rcc, "10"), ra=False)  # 52.5 billed
    assert problem(act(w, draft.json(), "issue")) == (422, "exceeds_boq_quantity")


@pytest.mark.parametrize(
    ("body", "field", "code"),
    [
        ({"project_id": None}, "project_id", "required"),
        ({"doc_type": "QUOTATION"}, "is_ra_bill", "not_allowed"),
        ({"lines": "plain"}, "lines[1].boq_item_id", "required"),
        ({"lines": "twice"}, "lines[1].boq_item_id", "duplicate_boq_item"),
    ],
)
def test_ra_bill_rules(w: Ra, body: dict[str, Any], field: str, code: str) -> None:
    lines = [{"boq_item_id": str(w.rcc.pk), "quantity": "1"}]
    if body.get("lines") == "plain":
        lines.append({"description": "Cleaning", "quantity": "1", "rate": "500.00"})
    elif body.get("lines") == "twice":
        lines.append({"boq_item_id": str(w.rcc.pk), "quantity": "2"})
    r = w.create(is_ra_bill=True, **{**body, "lines": lines})
    assert r.status_code == 422, r.content
    assert (r.json()["errors"][0]["field"], r.json()["errors"][0]["code"]) == (field, code)


def test_one_open_ra_draft_per_project_and_numbers_after_cancel(w: Ra) -> None:
    first = w.issued((w.rcc, "10"))
    draft = w.bill((w.rcc, "1")).json()
    assert problem(w.bill((w.rcc, "1"))) == (409, "ra_draft_exists")
    assert w.bill((w.rcc, "1"), ra=False).status_code == 201  # plain invoices are not limited
    APIClient().delete(f"/api/v1/documents/{draft['id']}", **w.h())
    second = w.issued((w.rcc, "5"))
    assert second["ra_sequence"] == 2
    act(w, second, "cancel", body={"reason": "wrong measurement"})
    assert w.issued((w.rcc, "6"))["ra_sequence"] == 2  # the latest cancelled: number reused
    act(w, first, "cancel", body={"reason": "duplicate"})
    assert w.bill((w.rcc, "1")).json()["ra_sequence"] == 3  # an earlier one: not reused


def test_turning_ra_on_and_off_on_a_draft(w: Ra) -> None:
    draft = w.bill((w.rcc, "10"), ra=False).json()
    url = f"/api/v1/documents/{draft['id']}"
    on = APIClient().patch(url, {"is_ra_bill": True}, format="json", **w.h(IF_MATCH='"v1"'))
    assert (on.status_code, on.json()["ra_sequence"]) == (200, 1), on.content
    assert on.json()["lines"][0]["prev_cumulative_qty"] == "0.000"
    again = APIClient().patch(url, {"notes": "x"}, format="json", **w.h(IF_MATCH='"v2"'))
    assert again.json()["ra_sequence"] == 1  # kept
    off = APIClient().patch(url, {"is_ra_bill": False}, format="json", **w.h(IF_MATCH='"v3"'))
    assert (off.json()["is_ra_bill"], off.json()["ra_sequence"]) == (False, None)
    assert off.json()["lines"][0]["prev_cumulative_qty"] is None


def test_ra_proforma_converts_to_an_ra_invoice_and_notes_are_not_ra(w: Ra) -> None:
    series(w, "PROFORMA", "PI/")
    proforma = w.issued((w.rcc, "20"), doc_type="PROFORMA")
    assert proforma["ra_sequence"] == 1
    assert w.bill((w.rcc, "1")).json()["ra_sequence"] == 1  # invoices number separately


def test_convert_and_credit_note(w: Ra) -> None:
    series(w, "PROFORMA", "PI/")
    proforma = w.issued((w.rcc, "20"), doc_type="PROFORMA")
    converted = act(w, proforma, "convert", body={"to": "TAX_INVOICE", "doc_date": "2026-10-20"})
    assert converted.status_code == 201, converted.content
    invoice = converted.json()
    assert (invoice["is_ra_bill"], invoice["ra_sequence"]) == (True, 1)
    issued = act(w, invoice, "issue").json()
    note = act(w, issued, "credit-notes", body={"doc_date": "2026-10-21"})
    assert note.status_code == 201, note.content
    assert (note.json()["is_ra_bill"], note.json()["ra_sequence"]) == (False, None)
    # proformas and credit notes do not count as billed quantity
    progress = APIClient().get(f"/api/v1/projects/{w.project.pk}/boq-progress", **w.h()).json()
    assert progress["results"][0]["billed_qty"] == "20.000"


def test_boq_progress(w: Ra) -> None:
    w.issued((w.rcc, "42.500"), (w.brick, "200"))
    w.issued((w.extra, "12"), ra=False)
    w.bill((w.rcc, "10"))  # drafts do not count
    r = APIClient().get(f"/api/v1/projects/{w.project.pk}/boq-progress", **w.h())
    assert r.status_code == 200, r.content
    rows = {row["item_code"]: row for row in r.json()["results"]}
    assert [
        rows["2.1"][k] for k in ("contract_qty", "billed_qty", "balance_qty", "progress_pct")
    ] == [
        "100.000",
        "42.500",
        "57.500",
        "42.50",
    ]
    assert (rows["2.1"]["contract_value"], rows["2.1"]["billed_value"]) == (
        "680000.00",
        "289000.00",
    )
    assert (rows["V1"]["balance_qty"], rows["V1"]["progress_pct"]) == ("-2.000", "120.00")
    # contract 680000 + 450000 + 10000; billed 289000 + 180000 + 12000
    assert r.json()["totals"] == {
        "contract_value": "1140000.00",
        "billed_value": "481000.00",
        "progress_pct": "42.19",
    }
    assert (
        APIClient().get(f"/api/v1/projects/{uuid.uuid4()}/boq-progress", **w.h()).status_code == 404
    )


def test_contract_quantity_cannot_go_below_billed(w: Ra) -> None:
    w.issued((w.rcc, "42.500"))
    w.issued((w.extra, "12"), ra=False)
    api, url = APIClient(), f"/api/v1/boq-items/{w.rcc.pk}"
    r = api.patch(url, {"contract_qty": "40.000"}, format="json", **w.h(IF_MATCH='"v1"'))
    assert problem(r) == (422, "below_billed")
    ok = api.patch(url, {"contract_qty": "42.500"}, format="json", **w.h(IF_MATCH='"v1"'))
    assert ok.status_code == 200, ok.content
    r = api.patch(
        f"/api/v1/boq-items/{w.extra.pk}",
        {"is_variation": False},
        format="json",
        **w.h(IF_MATCH='"v1"'),
    )
    assert (r.status_code, r.json()["errors"][0]["field"]) == (422, "is_variation")


def test_pdf_shows_ra_number_and_quantity_columns(w: Ra) -> None:
    w.issued((w.rcc, "42.500"))
    second = w.issued((w.rcc, "30"))
    with tenant_context(w.t.tenant_id, w.t.user_id):
        doc = Document.objects.get(pk=second["id"])
        ctx = build_context(doc)
        html = render_html(doc)
    assert ctx["ra_sequence"] == 2
    line = ctx["lines"][0]
    assert (line["item_code"], line["previous"], line["quantity"], line["up_to_date"]) == (
        "2.1",
        "42.5",
        "30",
        "72.5",
    )
    assert "RA Bill No. 2" in html
    assert "Previous qty" in html
    assert "Discount" not in html  # no line has a discount


def test_preview_totals_shows_previous_quantities(w: Ra) -> None:
    w.issued((w.rcc, "42.500"))
    r = APIClient().post(
        "/api/v1/documents:preview-totals",
        {
            "doc_type": "TAX_INVOICE",
            "party_id": str(w.client.pk),
            "project_id": str(w.project.pk),
            "doc_date": "2026-10-20",
            "is_ra_bill": True,
            "lines": [{"boq_item_id": str(w.rcc.pk), "quantity": "5"}],
        },
        format="json",
        **w.h(),
    )
    assert r.status_code == 200, r.content
    assert r.json()["lines"][0]["prev_cumulative_qty"] == "42.500"
