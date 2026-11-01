"""The statement of account as a file (W.1): CSV, XLSX and PDF exports."""

import csv
import io
from typing import Any

import pytest
from openpyxl import load_workbook
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.exports import statement_pdf
from apps.exports.models import Export
from apps.parties.models import Party
from tests.pdf.test_pdf import _weasyprint_works
from tests.reports.test_statement import Ledger

pytestmark = pytest.mark.django_db

MONTH = {"from": "2026-10-01", "to": "2026-11-30"}


@pytest.fixture
def ledger() -> Ledger:
    return Ledger()


def request(w: Ledger, file_format: str, **params: Any) -> Any:
    return APIClient().post(
        "/api/v1/exports",
        {"kind": "STATEMENT", "format": file_format, "params": params},
        format="json",
        **w.h(),
    )


def made(s3: Any, w: Ledger, response: Any) -> tuple[dict[str, Any], bytes]:
    assert response.status_code == 202, response.content
    body = APIClient().get(f"/api/v1/exports/{response.json()['id']}", **w.h()).json()
    assert body["status"] == "READY", body
    with tenant_context(w.t.tenant_id, w.t.user_id):
        key = Export.objects.get(pk=body["id"]).storage_key
    return body, s3.get_object(Bucket="test-bucket", Key=key)["Body"].read()


def test_statement_as_csv(s3: Any, ledger: Ledger, run: Any) -> None:
    with run():
        r = request(ledger, "CSV", party_id=str(ledger.client.pk), **MONTH)
    body, data = made(s3, ledger, r)
    assert body["file_name"] == "statement_skyline-developers_2026-10-01_2026-11-30.csv"
    assert body["params"] == {"party_id": str(ledger.client.pk), **MONTH}
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    assert rows[0] == ["Date", "Type", "Reference", "Description", "Debit", "Credit", "Balance"]
    assert rows[1] == ["2026-10-01", "", "", "Opening balance", "", "", "0.00"]
    assert rows[2][1:] == [
        "Payment",
        "ADV-1",
        "Payment received · Bank transfer · ADV-1",
        "",
        "100000.00",
        "-100000.00",
    ]
    assert [r[6] for r in rows[2:-1]] == [
        "-100000.00",
        "223680.00",
        "547360.00",
        "871040.00",
        "571040.00",
        "563016.00",
        "583016.00",
    ]
    assert rows[-1] == [
        "2026-11-30",
        "",
        "",
        "Closing balance",
        "991040.00",
        "408024.00",
        "583016.00",
    ]


def test_statement_as_xlsx(s3: Any, ledger: Ledger, run: Any) -> None:
    with run():
        r = request(ledger, "XLSX", party_id=str(ledger.client.pk), **MONTH)
    body, data = made(s3, ledger, r)
    assert body["row_count"] == 9  # opening + 7 entries + closing
    sheet = load_workbook(io.BytesIO(data)).active
    assert sheet is not None
    assert sheet["G9"].value == pytest.approx(583016)
    assert sheet["G9"].number_format == "#,##0.00"


def test_statement_pdf_page(ledger: Ledger) -> None:
    with tenant_context(ledger.t.tenant_id, ledger.t.user_id):
        Party.objects.filter(pk=ledger.client.pk).update(display_name="<b>Skyline</b>")
        html = statement_pdf.render_html(
            ledger.t.tenant_id, {"party_id": str(ledger.client.pk), **MONTH}
        )
    assert "Statement of Account" in html
    assert "01 Oct 2026 to 30 Nov 2026" in html
    assert "Closing balance: ₹5,83,016.00 due from you" in html
    assert "&lt;b&gt;Skyline&lt;/b&gt;" in html  # escaped
    assert "<b>Skyline</b>" not in html
    assert html.count("<tr>") == 1 + 7  # the header and the 7 entries


@pytest.mark.skipif(not _weasyprint_works(), reason="WeasyPrint system libraries not installed")
def test_statement_as_pdf(s3: Any, ledger: Ledger, run: Any) -> None:
    with run():
        r = request(ledger, "PDF", party_id=str(ledger.client.pk), **MONTH)
    body, data = made(s3, ledger, r)
    assert body["file_name"].endswith(".pdf")
    assert data.startswith(b"%PDF")


def test_statement_requests_are_checked(s3: Any, ledger: Ledger) -> None:
    for body, field in (
        ({"kind": "STATEMENT", "format": "CSV", "params": {}}, "params.party_id"),
        ({"kind": "PAYMENTS", "format": "PDF", "params": {}}, "format"),
        (
            {
                "kind": "STATEMENT",
                "format": "PDF",
                "params": {"party_id": "0192f5c4-0000-7000-8000-000000000099"},
            },
            "params.party_id",
        ),
    ):
        r = APIClient().post("/api/v1/exports", body, format="json", **ledger.h())
        assert r.status_code == 422, body
        assert r.json()["errors"][0]["field"] == field
