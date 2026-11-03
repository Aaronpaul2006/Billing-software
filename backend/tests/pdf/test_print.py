"""The complete PDF (B.13): logo, bank details, UPI QR, HSN summary, layouts,
copy labels, signature; print settings frozen when the bill is issued."""

import base64
import uuid
from decimal import Decimal
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.documents.models import Document
from apps.documents.pdf import render
from apps.files.models import Attachment
from apps.tenants.models import DocumentSeries, PrintSettings
from tests.documents.test_drafts import RCC, World
from tests.pdf.test_pdf import FAKE_PDF, html_of, issued

pytestmark = pytest.mark.django_db

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
BANK = {
    "bank_account_name": "Nair Constructions",
    "bank_name": "State Bank of India",
    "bank_account_number": "301234567890",
    "bank_ifsc": "SBIN0070123",
    "bank_branch": "Kakkanad",
    "upi_id": "nair@okaxis",
}


@pytest.fixture
def w() -> World:
    world = World()
    with tenant_context(world.t.tenant_id, world.t.user_id):
        for doc_type, prefix in (("TAX_INVOICE", "INV/"), ("QUOTATION", "QT/")):
            DocumentSeries.objects.create(
                gst_registration_id=world.t.registration_id,
                doc_type=doc_type,
                fy_start_year=2026,
                prefix=prefix,
            )
    return world


def settings(w: World, **kw: Any) -> None:
    with tenant_context(w.t.tenant_id, w.t.user_id):
        PrintSettings.objects.update_or_create(tenant_id=w.t.tenant_id, defaults=kw)


def stored_image(w: World, s3: Any) -> str:
    key = f"tenants/{w.t.tenant_id}/uploads/{uuid.uuid4()}.png"
    s3.put_object(Bucket="test-bucket", Key=key, Body=PNG, ContentType="image/png")
    with tenant_context(w.t.tenant_id, w.t.user_id):
        a = Attachment.objects.create(
            storage_key=key,
            original_filename="logo.png",
            content_type="image/png",
            size_bytes=len(PNG),
            status="AVAILABLE",
            uploaded_by_id=w.t.user_id,
        )
    return str(a.pk)


def context(w: World, doc_id: str, copy: str | None = None) -> dict[str, Any]:
    with tenant_context(w.t.tenant_id, w.t.user_id):
        return render.build_context(Document.objects.get(pk=doc_id), copy)


def test_the_upi_link_carries_the_exact_amount_and_bill_number() -> None:
    assert render.upi_link("nair@okaxis", "Nair Constructions", Decimal("323680"), "INV/0001") == (
        "upi://pay?pa=nair%40okaxis&pn=Nair%20Constructions&am=323680.00&cu=INR&tn=INV%2F0001"
    )


def test_bank_details_upi_qr_logo_and_signature(w: World, s3: Any) -> None:
    logo, sign = stored_image(w, s3), stored_image(w, s3)
    settings(w, **BANK, logo_attachment_id=logo, signature_attachment_id=sign)
    doc = issued(w)
    c = context(w, doc["id"])
    assert c["logo"] == c["signature"] == "data:image/png;base64," + base64.b64encode(PNG).decode()
    assert c["bank"]["bank_ifsc"] == "SBIN0070123"
    assert c["upi_qr"].startswith("data:image/svg+xml")
    assert c["upi_amount"] == render.inr(Decimal(doc["totals"]["net_receivable"]))
    html = html_of(w, doc["id"])
    for expected in ("Pay to", "A/c No.: <strong>301234567890</strong>", "UPI: nair@okaxis"):
        assert expected in html, expected
    assert f"Scan to pay ₹{c['upi_amount']}" in html
    assert 'alt="UPI QR code"' in html


def test_no_qr_on_drafts_quotations_or_cancelled_bills(w: World) -> None:
    settings(w, **BANK)
    draft = w.create().json()
    assert context(w, draft["id"])["upi_qr"] is None  # not payable until issued
    quote = issued(w, doc_type="QUOTATION", valid_until="2026-11-30")
    q = context(w, quote["id"])
    assert (q["bank"], q["upi_qr"]) == (None, None)


def test_settings_are_frozen_when_the_bill_is_issued(w: World) -> None:
    settings(w, **BANK)
    doc = issued(w)
    settings(w, bank_name="Another Bank", layout="SIMPLE")
    c = context(w, doc["id"])
    assert (c["bank"]["bank_name"], c["detailed"]) == ("State Bank of India", True)
    # a new bill uses the new settings
    later = issued(w)
    c = context(w, later["id"])
    assert (c["bank"]["bank_name"], c["detailed"]) == ("Another Bank", False)


def test_detailed_has_the_hsn_summary_simple_one_table(w: World) -> None:
    beams = {**RCC, "description": "Steel", "sac_hsn": "7214", "gst_rate": "18.00"}
    doc = issued(w, lines=[RCC, {**RCC, "description": "Beams"}, beams])
    c = context(w, doc["id"])
    assert [(r["hsn"], r["rate"]) for r in c["hsn_summary"]] == [("7214", "18"), ("9954", "18")]
    assert c["hsn_summary"][1]["taxable"] == "5,78,000.00"  # two RCC lines together
    html = html_of(w, doc["id"])
    assert '<table class="hsn"' in html
    assert "Total tax" in html
    settings(w, layout="SIMPLE")
    simple = issued(w)
    html = html_of(w, simple["id"])
    assert '<table class="lines simple">' in html
    assert '<table class="hsn"' not in html
    assert "GST %" not in html
    assert "9954" in html  # HSN / SAC stays on a tax invoice


def test_copy_labels_follow_rule_48(w: World) -> None:
    services = issued(w)
    assert context(w, services["id"])["copy_label"] == ""
    assert context(w, services["id"], "original")["copy_label"] == "Original for recipient"
    assert context(w, services["id"], "duplicate")["copy_label"] == "Duplicate for supplier"
    goods = issued(w, lines=[{**RCC, "sac_hsn": "2523", "description": "Cement"}])
    assert context(w, goods["id"], "duplicate")["copy_label"] == "Duplicate for transporter"
    assert context(w, goods["id"], "triplicate")["copy_label"] == "Triplicate for supplier"
    assert '<div class="copy">Original for recipient</div>' in _html(w, services["id"], "original")


def _html(w: World, doc_id: str, copy: str) -> str:
    with tenant_context(w.t.tenant_id, w.t.user_id):
        return render.render_html(Document.objects.get(pk=doc_id), copy)


def test_the_pdf_endpoint_prints_a_chosen_copy(w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.documents import views

    asked: list[str | None] = []

    def fake(doc: Document, copy: str | None = None) -> bytes:
        asked.append(copy)
        return FAKE_PDF

    monkeypatch.setattr(views, "render_pdf", fake)
    doc = issued(w)
    url = f"/api/v1/documents/{doc['id']}/pdf"
    r = APIClient().get(f"{url}?copy=original", **w.h())
    assert (r.status_code, r["Content-Type"], r.content) == (200, "application/pdf", FAKE_PDF)
    assert 'filename="tax_invoice-INV-0001-original.pdf"' in r["Content-Disposition"]
    assert asked == ["original"]
    bad = APIClient().get(f"{url}?copy=fourth", **w.h())
    assert (bad.status_code, bad.json()["errors"][0]["code"]) == (422, "invalid_choice")
    both = APIClient().get(f"{url}?copy=original&as=link", **w.h())
    assert (both.status_code, both.json()["errors"][0]["code"]) == (422, "copy")
