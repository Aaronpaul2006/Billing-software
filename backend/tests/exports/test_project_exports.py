"""K.3: the BOQ progress of one project, and the project margins report, as files."""

import csv
import io
import uuid
from typing import Any

import pytest
from openpyxl import load_workbook
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.exports.models import Export
from tests.documents.test_ra_bills import Ra
from tests.factories import add_member

pytestmark = pytest.mark.django_db


@pytest.fixture
def w() -> Ra:
    return Ra()


def request(w: Ra, member: Any = None, **body: Any) -> Any:
    return APIClient().post("/api/v1/exports", body, format="json", **w.h(member))


def fetch(s3: Any, w: Ra, export_id: str) -> tuple[dict[str, Any], bytes]:
    body = APIClient().get(f"/api/v1/exports/{export_id}", **w.h()).json()
    with tenant_context(w.t.tenant_id, w.t.user_id):
        key = Export.objects.get(pk=export_id).storage_key
    assert key, body
    data: bytes = s3.get_object(Bucket="test-bucket", Key=key)["Body"].read()
    return body, data


def test_boq_progress_as_csv(s3: Any, w: Ra, run: Any) -> None:
    w.issued((w.rcc, "42.500"), (w.brick, "200"))
    w.issued((w.extra, "12"), ra=False)
    with run():
        r = request(w, kind="BOQ", format="CSV", params={"project_id": str(w.project.pk)})
    assert r.status_code == 202, r.content
    assert r.json()["params"] == {"project_id": str(w.project.pk)}
    body, data = fetch(s3, w, r.json()["id"])
    assert body["status"] == "READY"
    assert body["row_count"] == 3
    assert body["file_name"].startswith(f"boq_{w.project.code}_")
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    by_code = {row["Item code"]: row for row in rows}
    rcc = by_code["2.1"]
    assert [rcc[k] for k in ("Contract qty", "Billed qty", "Balance qty", "Progress %")] == [
        "100",
        "42.5",
        "57.5",
        "42.5",
    ]
    assert (rcc["Rate"], rcc["Contract value"], rcc["Billed value"]) == (
        "6800.00",
        "680000.00",
        "289000.00",
    )
    assert (rcc["Unit"], rcc["Variation"]) == ("cum", "No")
    extra = by_code["V1"]  # a variation billed past its quantity
    assert (extra["Balance qty"], extra["Progress %"], extra["Variation"]) == ("-2", "120", "Yes")


def test_boq_progress_as_xlsx(s3: Any, w: Ra, run: Any) -> None:
    w.issued((w.rcc, "42.500"))
    with run():
        export_id = request(
            w, kind="BOQ", format="XLSX", params={"project_id": str(w.project.pk)}
        ).json()["id"]
    _, data = fetch(s3, w, export_id)
    sheet = load_workbook(io.BytesIO(data)).active
    assert sheet is not None
    header = [c.value for c in sheet[1]]
    row = {h: c for h, c in zip(header, sheet[2], strict=True)}
    assert row["Billed qty"].value == pytest.approx(42.5)
    assert row["Billed qty"].number_format == "#,##0.###"
    assert row["Billed value"].number_format == "#,##0.00"


def test_project_margins(s3: Any, w: Ra, run: Any) -> None:
    w.issued((w.rcc, "10"))  # 68000 before GST
    with run():
        r = request(w, kind="PROJECTS", format="CSV", params={"from": "2026-01-01"})
    assert r.status_code == 202, r.content
    assert r.json()["params"] == {}  # the report covers the whole life of each project
    body, data = fetch(s3, w, r.json()["id"])
    assert body["file_name"].startswith("project-margins_")
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    mine = next(row for row in rows if row["Code"] == w.project.code)
    assert mine["Billed (before GST)"] == "68000.00"
    assert mine["Cost"] == "0.00"
    assert mine["Margin"] == "68000.00"


def test_requests_are_checked(s3: Any, w: Ra) -> None:
    for params, message in (
        ({}, "Choose the project."),
        ({"project_id": str(uuid.uuid4())}, "No such project."),
    ):
        bad = request(w, kind="BOQ", format="CSV", params=params)
        assert bad.status_code == 422, params
        assert bad.json()["errors"][0]["field"] == "params.project_id"
        assert bad.json()["errors"][0]["message"] == message
    engineer = add_member(w.t, "SITE_ENGINEER")
    project = {"project_id": str(w.project.pk)}
    assert request(w, engineer, kind="BOQ", format="CSV", params=project).status_code == 403
    assert request(w, engineer, kind="PROJECTS", format="CSV").status_code == 403
