"""Exports: CSV / XLSX registers made in the background (docs/02-api-design.md §8)."""

import csv
import io
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.db import connection
from django.utils import timezone
from openpyxl import load_workbook
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.expenses.models import Expense
from apps.exports import builders, services
from apps.exports.models import Export
from apps.exports.tasks import purge_old_exports
from apps.files import storage
from apps.parties.models import Party
from apps.payments.models import Payment
from tests.documents.test_drafts import World
from tests.documents.test_lifecycle import act, series
from tests.factories import add_member

pytestmark = pytest.mark.django_db


@pytest.fixture
def w() -> World:
    world = World()
    with tenant_context(world.t.tenant_id, world.t.user_id):
        # A name a spreadsheet would run as a formula if it were not escaped.
        Party.objects.filter(pk=world.client.pk).update(display_name='=HYPERLINK("x")')
    return world


def request(w: World, member: Any = None, **body: Any) -> Any:
    return APIClient().post("/api/v1/exports", body, format="json", **w.h(member))


def fetch(s3: Any, w: World, export_id: str) -> tuple[dict[str, Any], bytes]:
    body = APIClient().get(f"/api/v1/exports/{export_id}", **w.h()).json()
    with tenant_context(w.t.tenant_id, w.t.user_id):
        key = Export.objects.get(pk=export_id).storage_key
    data: bytes = s3.get_object(Bucket="test-bucket", Key=key)["Body"].read() if key else b""
    return body, data


def issued_invoice(w: World) -> dict[str, Any]:
    series(w)
    issued: dict[str, Any] = act(w, w.create().json(), "issue").json()
    return issued


def test_invoice_register_as_csv(s3: Any, w: World, run: Any) -> None:
    invoice = issued_invoice(w)
    w.create()  # a draft: never exported
    with run():
        response = request(
            w, kind="DOCUMENTS", format="CSV", params={"from": "2026-10-01", "to": "2026-10-31"}
        )
    assert response.status_code == 202, response.content
    assert response.json()["status"] == "PENDING"
    body, data = fetch(s3, w, response.json()["id"])
    assert body["status"] == "READY"
    assert body["file_name"] == "invoice-register_2026-10-01_2026-10-31.csv"
    assert body["row_count"] == 1
    assert body["params"] == {"from": "2026-10-01", "to": "2026-10-31", "book": "ALL"}
    assert "response-content-disposition=attachment" in body["download_url"]
    assert data.startswith(b"\xef\xbb\xbf")  # BOM: Excel reads UTF-8
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    header, row = rows[0], rows[1]
    values = dict(zip(header, row, strict=True))
    assert values["Number"] == invoice["doc_number"]
    assert values["Type"] == "Tax Invoice"
    assert values["Status"] == "Issued"
    assert values["Client"] == '\'=HYPERLINK("x")'  # escaped, not a formula
    assert values["Place of supply"] == "32 Kerala"
    assert values["Total"] == invoice["totals"]["grand_total"]
    assert values["Outstanding"] == invoice["totals"]["net_receivable"]
    assert values["Date"] == "2026-10-19"


def test_invoice_register_as_xlsx(s3: Any, w: World, run: Any) -> None:
    invoice = issued_invoice(w)
    with run():
        export_id = request(
            w, kind="DOCUMENTS", format="XLSX", params={"from": "2026-10-01", "to": "2026-10-31"}
        ).json()["id"]
    body, data = fetch(s3, w, export_id)
    assert body["file_name"].endswith(".xlsx")
    sheet = load_workbook(io.BytesIO(data)).active
    assert sheet is not None
    header = [c.value for c in sheet[1]]
    row = {h: c for h, c in zip(header, sheet[2], strict=True)}
    assert sheet["A1"].font.bold
    assert row["Client"].value == '=HYPERLINK("x")'
    assert row["Client"].data_type == "s"  # stored as text, never evaluated
    assert row["Total"].value == pytest.approx(float(invoice["totals"]["grand_total"]))
    assert row["Total"].number_format == "#,##0.00"
    assert row["Date"].value == datetime(2026, 10, 19)  # noqa: DTZ001 - a naive spreadsheet date


def test_payments_expenses_and_receivables(s3: Any, w: World, run: Any) -> None:
    issued_invoice(w)
    with tenant_context(w.t.tenant_id, w.t.user_id):
        Payment.objects.create(
            party=w.client,
            payment_date=date(2026, 10, 20),
            amount=Decimal("1000.00"),
            mode="UPI",
            reference="UTR123",
            created_by_id=w.t.user_id,
        )
        Expense.objects.create(
            category="MATERIAL",
            expense_date=date(2026, 10, 20),
            description="-100 bags (negative-looking text)",
            taxable_value=Decimal("100.00"),
            gst_amount=Decimal("18.00"),
            total_amount=Decimal("118.00"),
            amount_paid=Decimal("18.00"),
            payment_mode="CASH",
            created_by_id=w.t.user_id,
        )
    dates = {"from": "2026-10-01", "to": "2026-10-31"}
    with run():
        ids = {
            kind: request(w, kind=kind, format="CSV", params=dates).json()["id"]
            for kind in ("PAYMENTS", "EXPENSES")
        }
        ids["RECEIVABLES"] = request(w, kind="RECEIVABLES", format="CSV").json()["id"]

    def table(kind: str) -> list[dict[str, str]]:
        _, data = fetch(s3, w, ids[kind])
        return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))

    [payment] = table("PAYMENTS")
    assert (payment["Mode"], payment["Amount"], payment["Unallocated"]) == (
        "UPI",
        "1000.00",
        "1000.00",
    )
    [expense] = table("EXPENSES")
    assert expense["Description"] == "'-100 bags (negative-looking text)"
    assert (expense["Total"], expense["Balance"], expense["Paid by"]) == (
        "118.00",
        "100.00",
        "Cash",
    )
    [owed] = table("RECEIVABLES")
    assert owed["Documents"] == "1"
    assert owed["Client"] == '\'=HYPERLINK("x")'


def test_defaults_and_validation(s3: Any, w: World) -> None:
    today = timezone.localdate()
    response = request(w, kind="PAYMENTS", format="XLSX")
    assert response.status_code == 202
    params = response.json()["params"]
    assert params["to"] == today.isoformat()
    assert params["from"].endswith("-04-01")  # this financial year
    for body, field in (
        ({"kind": "GSTR1", "format": "CSV"}, "format"),
        ({"kind": "TAX_RETURN", "format": "CSV"}, "kind"),
        ({"kind": "PAYMENTS", "format": "PDF"}, "format"),
        (
            {
                "kind": "PAYMENTS",
                "format": "CSV",
                "params": {"from": "2026-10-02", "to": "2026-10-01"},
            },
            "params.from",
        ),
    ):
        bad = request(w, **body)
        assert bad.status_code == 422, body
        assert bad.json()["errors"][0]["field"] == field


def test_roles_and_privacy(s3: Any, w: World) -> None:
    engineer = add_member(w.t, "SITE_ENGINEER")
    assert request(w, engineer, kind="PAYMENTS", format="CSV").status_code == 403
    viewer = add_member(w.t, "VIEWER")
    mine = request(w, viewer, kind="PAYMENTS", format="CSV").json()["id"]
    # Another member's export is theirs: not listed for the owner, and 404.
    assert APIClient().get(f"/api/v1/exports/{mine}", **w.h()).status_code == 404
    assert APIClient().get("/api/v1/exports", **w.h()).json()["results"] == []
    listed = APIClient().get("/api/v1/exports", **w.h(viewer)).json()["results"]
    assert [x["id"] for x in listed] == [mine]


def test_rate_limited(s3: Any, w: World, settings: Any) -> None:
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, "export_user": (2, 3600)}
    codes = [request(w, kind="PAYMENTS", format="CSV").status_code for _ in range(3)]
    assert codes == [202, 202, 429]


def test_failures_are_reported(
    s3: Any, w: World, run: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builders, "MAX_ROWS", -1)
    with run():
        too_big = request(w, kind="PAYMENTS", format="CSV").json()["id"]
    body, _ = fetch(s3, w, too_big)
    assert body["status"] == "FAILED"
    assert "choose a shorter period" in body["error"]
    assert body["download_url"] is None

    def broken(tenant_id: uuid.UUID, params: dict[str, Any]) -> Any:
        raise RuntimeError("bug")

    monkeypatch.setitem(builders.BUILDERS, "EXPENSES", broken)
    with run():
        crashed = request(w, kind="EXPENSES", format="CSV").json()["id"]
    body, _ = fetch(s3, w, crashed)
    assert (body["status"], body["error"]) == (
        "FAILED",
        "The file could not be made. Try again, or tell support.",
    )


def test_exports_are_purged_after_seven_days(s3: Any, w: World, run: Any) -> None:
    with run():
        old = request(w, kind="PAYMENTS", format="CSV").json()["id"]
        new = request(w, kind="PAYMENTS", format="CSV").json()["id"]
    with tenant_context(w.t.tenant_id, w.t.user_id):
        key = Export.objects.get(pk=old).storage_key
        Export.objects.filter(pk=old).update(created_at=timezone.now() - timedelta(days=8))
    assert purge_old_exports() == 1
    assert storage.head(str(key)) is None
    with tenant_context(w.t.tenant_id, w.t.user_id):
        assert list(Export.objects.values_list("pk", flat=True)) == [uuid.UUID(new)]
    with connection.cursor() as cursor:  # no tenant: the app role sees none
        cursor.execute("SELECT count(*) FROM exports")
        assert cursor.fetchone()[0] == 0


def test_run_export_is_idempotent(s3: Any, w: World, run: Any) -> None:
    with run():
        export_id = request(w, kind="PAYMENTS", format="CSV").json()["id"]
    with tenant_context(w.t.tenant_id, w.t.user_id):
        key = Export.objects.get(pk=export_id).storage_key
        assert services.run_export(uuid.UUID(export_id)) == "READY"  # a retried task
        assert Export.objects.get(pk=export_id).storage_key == key  # nothing written again
