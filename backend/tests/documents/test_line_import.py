"""Bill lines from a file or from cells pasted out of Excel (B.7): checked, never saved."""

from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.documents.models import Document
from tests.documents.test_drafts import World
from tests.factories import add_member

pytestmark = pytest.mark.django_db


@pytest.fixture
def w() -> World:
    return World()


def paste(w: World, text: str, member: Any = None) -> Any:
    return APIClient().post(
        "/api/v1/documents:parse-lines", {"text": text}, format="json", **w.h(member)
    )


def errors(r: Any) -> list[tuple[str | None, str]]:
    body = r.json()
    return [(e["field"], e["code"]) for e in body.get("errors", [])] or [(None, body["code"])]


def test_pasted_cells_with_a_header_row(w: World) -> None:
    text = (
        "Particulars\tQty\tUOM\tRate (₹)\tDiscount %\tGST %\tHSN\n"
        'Excavation in ordinary soil\t120\tcum\t"1,250.50"\t5\t18\t9954\n'
        "Total\t\t\t\t\t\t\n"  # a total row: no quantity, skipped
    )
    r = paste(w, text)
    assert r.status_code == 200, r.content
    body = r.json()
    assert (body["count"], body["dry_run"], body["skipped_rows"]) == (1, True, [3])
    assert body["lines"] == [
        {
            "description": "Excavation in ordinary soil",
            "sac_hsn": "9954",
            "unit": "cum",
            "quantity": "120.000",
            "rate": "1250.50",
            "discount_amount": None,
            "discount_pct": "5.00",
            "gst_rate": "18.00",
        }
    ]
    with tenant_context(w.t.tenant_id, w.t.user_id):
        assert Document.objects.count() == 0  # nothing saved


def test_pasted_cells_without_a_header_use_the_paste_order(w: World) -> None:
    r = paste(
        w, "Brickwork in CM 1:6\t300\tsqm\t850\t18\t9954\nPlastering\t280.5\tsqm\t310\t18\t\n"
    )
    assert r.status_code == 200, r.content
    lines = r.json()["lines"]
    assert [(ln["description"], ln["quantity"], ln["rate"]) for ln in lines] == [
        ("Brickwork in CM 1:6", "300.000", "850.00"),
        ("Plastering", "280.500", "310.00"),
    ]
    assert lines[1]["sac_hsn"] is None


def test_every_bad_row_is_named_and_no_line_comes_back(w: World) -> None:
    text = "Description\tQty\tRate\nGood line\t2\t100\nNo rate\t3\t\nBad qty\tabc\t50\n"
    r = paste(w, text)
    assert r.status_code == 422
    assert errors(r) == [("rows[3].rate", "required"), ("rows[4].quantity", "invalid")]


def test_a_csv_or_excel_file_works_too(w: World) -> None:
    csv = b"Description,Quantity,Unit,Rate,GST %\nWaterproofing,40,sqm,220,18\n"
    r = APIClient().post(
        "/api/v1/documents:parse-lines",
        {"file": SimpleUploadedFile("lines.csv", csv)},
        format="multipart",
        **w.h(),
    )
    assert r.status_code == 200, r.content
    assert r.json()["lines"][0]["description"] == "Waterproofing"

    sample = APIClient().get("/api/v1/documents:lines-sample", {"type": "xlsx"}, **w.h())
    assert sample.status_code == 200
    r = APIClient().post(
        "/api/v1/documents:parse-lines",
        {"file": SimpleUploadedFile("s.xlsx", sample.content)},
        format="multipart",
        **w.h(),
    )
    assert r.status_code == 200, r.content
    assert r.json()["count"] == 2


def test_send_a_file_or_text(w: World) -> None:
    r = APIClient().post("/api/v1/documents:parse-lines", {}, format="json", **w.h())
    assert (r.status_code, errors(r)) == (422, [("file", "required")])


def test_roles_that_may_draft_bills(w: World) -> None:
    assert paste(w, "A\t1\tnos\t5\n", add_member(w.t, "SITE_ENGINEER")).status_code == 200
    assert paste(w, "A\t1\tnos\t5\n", add_member(w.t, "VIEWER")).status_code == 403
