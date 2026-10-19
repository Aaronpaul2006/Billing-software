"""Document PDFs: content, escaping, storage (moto S3), endpoint, issue → task."""

import importlib.util
import uuid
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlparse

import boto3
import pytest
from django.test import override_settings
from moto import mock_aws
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.documents.models import Document
from apps.documents.pdf import render
from apps.documents.services import pdfs
from apps.files import storage
from apps.files.models import Attachment
from apps.parties.models import Party
from apps.tenants.models import DocumentSeries
from tests.documents.test_drafts import World

pytestmark = pytest.mark.django_db
FAKE_PDF = b"%PDF-1.7 test"


def _weasyprint_works() -> bool:
    if importlib.util.find_spec("weasyprint") is None:
        return False
    try:
        import weasyprint  # noqa: F401
    except OSError:  # Pango system libraries missing (e.g. Windows without GTK)
        return False
    return True


@pytest.fixture
def w() -> World:
    world = World()
    with tenant_context(world.t.tenant_id, world.t.user_id):
        DocumentSeries.objects.create(
            gst_registration_id=world.t.registration_id,
            doc_type="TAX_INVOICE",
            fy_start_year=2026,
            prefix="INV/",
        )
    return world


def issued(w: World, **kw: Any) -> dict[str, Any]:
    doc = w.create(**kw).json()
    response = APIClient().post(
        f"/api/v1/documents/{doc['id']}/issue",
        {},
        format="json",
        **w.h(IF_MATCH='"v1"', IDEMPOTENCY_KEY=str(uuid.uuid4())),
    )
    assert response.status_code == 200, response.content
    return dict(response.json())


def load(w: World, doc_id: str) -> Document:
    with tenant_context(w.t.tenant_id, w.t.user_id):
        doc: Document = Document.objects.get(pk=doc_id)
    return doc


def html_of(w: World, doc_id: str) -> str:
    with tenant_context(w.t.tenant_id, w.t.user_id):
        return render.render_html(Document.objects.get(pk=doc_id))


# --- content -------------------------------------------------------------------------------


def test_indian_digit_grouping() -> None:
    assert render.inr(Decimal("341020")) == "3,41,020.00"
    assert render.inr(Decimal("12345678.9")) == "1,23,45,678.90"
    assert render.inr(Decimal("999")) == "999.00"
    assert render.inr(Decimal("-0.48")) == "-0.48"


def test_tax_invoice_carries_the_rule_46_particulars(w: World) -> None:
    doc = issued(w)
    html = html_of(w, doc["id"])
    for expected in (
        "Tax Invoice",
        "INV/0001",
        "19-10-2026",  # title, number, date
        "Nair Constructions",
        (load(w, doc["id"]).supplier_snapshot or {})["gstin"],  # supplier
        "Skyline Developers",
        w.client.gstin,  # recipient
        "Place of supply: 32 - Kerala",
        "Reverse charge: No",
        "9954",
        "42.5",
        "cum",
        "2,89,000.00",  # HSN, qty, unit, taxable
        "CGST",
        "SGST",
        "26,010.00",
        "3,41,020.00",  # tax and total
        "Rupees Three Lakh Forty-One Thousand Twenty Only",  # total in words
        "Less: Retention",
        "Net receivable",
        "Authorised signatory",
    ):
        assert str(expected) in html, expected
    assert "IGST" not in html  # intra-state


def test_party_names_are_escaped(w: World) -> None:
    with tenant_context(w.t.tenant_id, w.t.user_id):
        Party.objects.filter(pk=w.client.pk).update(display_name="<script>alert(1)</script>")
    doc = issued(w)
    html = html_of(w, doc["id"])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_drafts_are_watermarked(w: World) -> None:
    draft = w.create().json()
    assert '<div class="watermark">DRAFT</div>' in html_of(w, draft["id"])


@pytest.mark.skipif(not _weasyprint_works(), reason="WeasyPrint system libraries not installed")
def test_real_pdf_is_produced(w: World) -> None:
    doc = load(w, issued(w)["id"])
    with tenant_context(w.t.tenant_id, w.t.user_id):  # as in the task / request
        pdf = render.render_pdf(doc)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 5000


# --- storage, endpoint -----------------------------------------------------------------


@pytest.fixture
def s3() -> Iterator[Any]:
    with (
        mock_aws(),
        override_settings(
            S3_ENDPOINT_URL=None,
            S3_PUBLIC_ENDPOINT_URL=None,
            S3_REGION="us-east-1",
            S3_BUCKET="test-bucket",
        ),
    ):
        storage._client.cache_clear()
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-bucket")
        yield client
    storage._client.cache_clear()


@pytest.fixture
def fake_render(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdfs, "render_pdf", lambda doc: FAKE_PDF)


@pytest.mark.usefixtures("fake_render")
def test_store_pdf_uploads_records_and_links_once(w: World, s3: Any) -> None:
    doc = issued(w)
    with tenant_context(w.t.tenant_id, w.t.user_id):
        first = pdfs.store_pdf(uuid.UUID(doc["id"]), w.t.user_id)
        again = pdfs.store_pdf(uuid.UUID(doc["id"]), w.t.user_id)
        attachment = Attachment.objects.get(pk=first)
    assert first == again  # idempotent
    assert (attachment.status, attachment.size_bytes, attachment.content_type) == (
        "AVAILABLE",
        len(FAKE_PDF),
        "application/pdf",
    )
    assert attachment.storage_key.startswith(f"tenants/{w.t.tenant_id}/documents/")
    assert attachment.original_filename == "tax_invoice-INV-0001.pdf"
    body = s3.get_object(Bucket="test-bucket", Key=attachment.storage_key)["Body"].read()
    assert body == FAKE_PDF
    assert load(w, doc["id"]).pdf_attachment_id == first


@pytest.mark.usefixtures("fake_render")
def test_pdf_endpoint(w: World, s3: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    queued: list[tuple[Any, ...]] = []
    monkeypatch.setattr(pdfs, "enqueue_pdf", lambda *a: queued.append(a))
    doc = issued(w)
    url = f"/api/v1/documents/{doc['id']}/pdf"

    pending = APIClient().get(url, **w.h())
    assert (pending.status_code, pending["Retry-After"]) == (202, "3")
    assert queued == [(w.t.tenant_id, w.t.user_id, uuid.UUID(doc["id"]))]

    with tenant_context(w.t.tenant_id, w.t.user_id):
        pdfs.store_pdf(uuid.UUID(doc["id"]), w.t.user_id)
    ready = APIClient().get(url, **w.h())
    assert ready.status_code == 302
    link = urlparse(ready["Location"])
    params = parse_qs(link.query)
    assert link.path.endswith("tax_invoice-INV-0001.pdf")
    assert "X-Amz-Signature" in params
    assert params["X-Amz-Expires"] == ["300"]


def test_draft_pdf_is_rendered_on_demand(w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.documents import views

    monkeypatch.setattr(views, "render_pdf", lambda doc: FAKE_PDF)
    draft = w.create().json()
    response = APIClient().get(f"/api/v1/documents/{draft['id']}/pdf", **w.h())
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content == FAKE_PDF
    assert load(w, draft["id"]).pdf_attachment_id is None  # never stored


@override_settings(RENDER_PDF_ON_ISSUE=True)
def test_issue_queues_rendering_after_commit(
    w: World,
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: Callable[..., Any],
) -> None:
    from apps.documents import tasks

    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(tasks.render_document_pdf, "delay", lambda *a: calls.append(a))
    with django_capture_on_commit_callbacks(execute=True):
        doc = issued(w)
    assert calls == [(str(w.t.tenant_id), str(w.t.user_id), doc["id"])]


@pytest.mark.usefixtures("fake_render")
def test_task_renders_inside_the_tenant_context(w: World, s3: Any) -> None:
    from apps.documents.tasks import render_document_pdf

    doc = issued(w)
    attachment_id = render_document_pdf.run(str(w.t.tenant_id), str(w.t.user_id), doc["id"])
    assert attachment_id is not None
    assert str(load(w, doc["id"]).pdf_attachment_id) == attachment_id
