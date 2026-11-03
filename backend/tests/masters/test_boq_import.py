"""BOQ import from CSV / XLSX (Phase 3.1)."""

import io
import uuid
import zipfile
from typing import Any

import openpyxl
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.core import sheets
from apps.core.tenancy import tenant_context
from apps.projects import boq_import
from apps.projects.models import BoqItem
from tests.documents.test_drafts import World
from tests.factories import add_member

pytestmark = pytest.mark.django_db

CSV = (
    "BOQ - Villa 1, Kakkanad\n"  # a title row above the header
    "\n"
    "Item No.,Description,UOM,Qty,Rate (₹),GST %,HSN/SAC,Amount\n"
    "1,EARTHWORK,,,,,,\n"  # a heading row
    '1.1,Excavation in ordinary soil,cum,120,"₹ 1,250.00",18,995453,150000\n'
    '1.2,"Backfilling, rammed",cum,80.5,450,18%,,36225\n'
    "2,M25 RCC for slabs,cum,42.500,6800,,,289000\n"
    ",Total,,,,,,475225\n"  # a subtotal row
)


class Boq(World):
    def upload(
        self,
        content: bytes | str,
        member: Any = None,
        key: str | None = None,
        name: str = "boq.csv",
        **form: Any,
    ) -> Any:
        data = content.encode() if isinstance(content, str) else content
        return APIClient().post(
            f"/api/v1/projects/{self.project.pk}/boq-items:import",
            {"file": SimpleUploadedFile(name, data), **form},
            format="multipart",
            **self.h(member, IDEMPOTENCY_KEY=key or str(uuid.uuid4())),
        )

    def codes(self) -> list[str]:
        with tenant_context(self.t.tenant_id, self.t.user_id):
            return list(
                BoqItem.objects.filter(project=self.project)
                .order_by("sort_order")
                .values_list("item_code", flat=True)
            )


@pytest.fixture
def w() -> Boq:
    return Boq()


def problem(r: Any) -> tuple[int, list[tuple[str | None, str]]]:
    b = r.json()
    return r.status_code, [(e["field"], e["code"]) for e in b.get("errors", [])] or [
        (None, b["code"])
    ]


def xlsx(rows: list[list[Any]]) -> bytes:
    book = openpyxl.Workbook()
    sheet = book.active
    assert sheet is not None
    for row in rows:
        sheet.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def test_csv_import_with_title_heading_and_total_rows(w: Boq) -> None:
    r = w.upload(CSV)
    assert r.status_code == 201, r.content
    body = r.json()
    assert (body["dry_run"], body["count"], body["skipped_rows"], body["ignored_columns"]) == (
        False,
        3,
        [4, 8],
        ["Amount"],
    )
    rows = [
        (i["item_code"], i["unit"], i["contract_qty"], i["rate"], i["gst_rate"], i["sac_hsn"])
        for i in body["items"]
    ]
    assert rows == [
        ("1.1", "cum", "120.000", "1250.00", "18.00", "995453"),
        ("1.2", "cum", "80.500", "450.00", "18.00", None),
        ("2", "cum", "42.500", "6800.00", "18.00", None),  # GST defaults to 18 %
    ]
    assert body["items"][1]["description"] == "Backfilling, rammed"
    assert w.codes() == ["1.1", "1.2", "2"]


def test_xlsx_import_with_numbers_as_excel_stores_them(w: Boq) -> None:
    data = xlsx(
        [
            ["Code", "Particulars", "Unit", "Quantity", "Rate", "GST", "Variation"],
            ["A1", "Plastering 12 mm", "sqm", 1250.75, 285.5, 18, "no"],
            [2.1, "Extra parapet", "rmt", 30, 900, 12, True],  # a numeric code
        ]
    )
    r = w.upload(data, name="anything.bin")  # type comes from content, not name
    assert r.status_code == 201, r.content
    items = r.json()["items"]
    assert [
        (i["item_code"], i["contract_qty"], i["rate"], i["gst_rate"], i["is_variation"])
        for i in items
    ] == [
        ("A1", "1250.750", "285.50", "18.00", False),
        ("2.1", "30.000", "900.00", "12.00", True),
    ]


def test_dry_run_saves_nothing(w: Boq) -> None:
    r = w.upload(CSV, dry_run="true")
    assert (r.status_code, r.json()["dry_run"], r.json()["count"]) == (200, True, 3)
    assert r.json()["items"][0]["id"] is None
    assert w.codes() == []


def test_all_or_nothing_with_row_numbers(w: Boq) -> None:
    bad = CSV.replace("cum,80.5,450", "cum,80.5,-450").replace("42.500,6800", "42.5001,6800")
    bad += "1.1,Duplicate code,nos,1,1,,,\n"
    status, errors = problem(w.upload(bad))
    assert status == 422
    assert errors == [
        ("rows[6].rate", "min_value"),
        ("rows[7].contract_qty", "max_decimal_places"),
        ("rows[9].item_code", "duplicate_item_code"),
    ]
    assert w.codes() == []


def test_codes_already_in_the_project(w: Boq) -> None:
    assert w.upload(CSV).status_code == 201
    status, errors = problem(w.upload(CSV))
    assert (status, errors[0]) == (422, ("rows[5].item_code", "item_code_taken"))
    assert len(w.codes()) == 3
    more = "item_code,description,unit,contract_qty,rate\n3,Shuttering,sqm,10,500\n"
    r = w.upload(more)
    assert r.json()["items"][0]["sort_order"] == 4  # appended after the existing items


@pytest.mark.parametrize(
    ("content", "code"),
    [
        ("Description,Qty\nx,1\n", "missing_columns"),
        ("item_code,description,unit,contract_qty,rate\n,,,,\n", "no_rows"),
        (b"\xff\xfeI\x00t\x00", "not_utf8"),
        (b"PK\x03\x04not really a zip", "unsupported_file"),
        ("item_code,description,unit,contract_qty,rate\n1,x,nos,1,abc\n", "invalid"),
    ],
)
def test_unreadable_files(w: Boq, content: Any, code: str) -> None:
    status, errors = problem(w.upload(content))
    assert status == 422
    assert errors[0][1] == code


def test_limits(w: Boq, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sheets, "MAX_ROWS", 2)  # the shared reader's limits
    assert problem(w.upload(CSV))[1][0] == ("file", "too_many_rows")
    monkeypatch.setattr(boq_import, "MAX_BYTES", 100)
    assert problem(w.upload(CSV))[1][0] == ("file", "file_too_large")


def test_zip_bomb_is_refused_before_parsing(w: Boq, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sheets, "MAX_UNCOMPRESSED", 1000)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/worksheets/sheet1.xml", "0" * 100_000)  # compresses to ~200 bytes
    assert problem(w.upload(out.getvalue()))[1][0] == ("file", "file_too_large")


def test_xlsx_parsing_uses_defusedxml() -> None:
    import openpyxl.xml

    assert openpyxl.xml.DEFUSEDXML


def test_idempotent_replay_covers_the_file(w: Boq) -> None:
    key = str(uuid.uuid4())
    first = w.upload(CSV, key=key)
    again = w.upload(CSV, key=key)
    assert (again.status_code, again["Idempotent-Replayed"]) == (201, "true")
    assert again.json() == first.json()
    other_file = w.upload(CSV.replace("Excavation", "Digging"), key=key)
    assert problem(other_file)[1][0][1] == "idempotency_key_reused"
    assert len(w.codes()) == 3


def test_roles_and_unknown_project(w: Boq) -> None:
    assert w.upload(CSV, member=add_member(w.t, "SITE_ENGINEER")).status_code == 201
    assert problem(w.upload(CSV, member=add_member(w.t, "VIEWER"))) == (
        403,
        [(None, "permission_denied")],
    )
    r = APIClient().post(
        f"/api/v1/projects/{uuid.uuid4()}/boq-items:import",
        {"file": SimpleUploadedFile("b.csv", CSV.encode())},
        format="multipart",
        **w.h(IDEMPOTENCY_KEY=str(uuid.uuid4())),
    )
    assert r.status_code == 404
