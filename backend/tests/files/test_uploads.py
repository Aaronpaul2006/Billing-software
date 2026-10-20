"""User uploads: presigned PUT, completion checks, virus scan (docs/02-api-design.md §7)."""

import hashlib
import socketserver
import struct
import threading
import uuid
from collections.abc import Callable, Iterator
from typing import Any, ClassVar
from urllib.parse import parse_qs, unquote, urlparse

import boto3
import pytest
from django.test import override_settings
from moto import mock_aws
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.files import scan, services, storage
from apps.files.models import Attachment
from tests.factories import TenantFixture, add_member, make_tenant, owner_member

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.7\n" + b"0" * 2000 + b"\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 100
EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


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


class Uploader:
    def __init__(self, t: TenantFixture, role: str = "SITE_ENGINEER") -> None:
        self.t = t
        member = owner_member(t) if role == "OWNER" else add_member(t, role)
        self.headers: dict[str, Any] = {"HTTP_AUTHORIZATION": f"Bearer {member.access_token}"}
        self.api = APIClient()

    def start(
        self, filename: str = "bill.pdf", ctype: str = "application/pdf", size: int = 0
    ) -> Any:
        body = {"filename": filename, "content_type": ctype, "size_bytes": size or len(PDF)}
        return self.api.post("/api/v1/attachments", body, format="json", **self.headers)

    def complete(self, attachment_id: str) -> Any:
        return self.api.post(f"/api/v1/attachments/{attachment_id}/complete", **self.headers)

    def get(self, attachment_id: str) -> Any:
        return self.api.get(f"/api/v1/attachments/{attachment_id}", **self.headers)


@pytest.fixture
def tenant() -> TenantFixture:
    return make_tenant()


@pytest.fixture
def me(tenant: TenantFixture) -> Uploader:
    return Uploader(tenant)


def key_of(attachment_id: str, t: TenantFixture) -> str:
    with tenant_context(t.tenant_id, t.user_id):
        return str(Attachment.objects.get(pk=attachment_id).storage_key)


def put(s3: Any, key: str, data: bytes, ctype: str = "application/pdf") -> None:
    """What the browser does with the presigned URL."""
    s3.put_object(Bucket="test-bucket", Key=key, Body=data, ContentType=ctype)


def upload(s3: Any, me: Uploader, run: Any, data: bytes = PDF, **start: Any) -> dict[str, Any]:
    started = me.start(**start)
    assert started.status_code == 201, started.content
    attachment_id = started.json()["attachment"]["id"]
    put(s3, key_of(attachment_id, me.t), data, start.get("ctype", "application/pdf"))
    with run():
        assert me.complete(attachment_id).status_code == 202
    body: dict[str, Any] = me.get(attachment_id).json()
    return body


@pytest.fixture
def run(django_capture_on_commit_callbacks: Any) -> Callable[[], Any]:
    """`with run():` runs the after-commit task (Celery is eager in tests)."""
    return lambda: django_capture_on_commit_callbacks(execute=True)


# --- start ---------------------------------------------------------------------------


def test_start_gives_a_presigned_put_for_exactly_this_type_and_size(s3: Any, me: Uploader) -> None:
    response = me.start(filename="../../site\t photo.pdf")
    assert response.status_code == 201, response.content
    body = response.json()
    attachment = body["attachment"]
    assert attachment["status"] == "PENDING"
    assert attachment["filename"] == "site photo.pdf"
    assert attachment["download_url"] is None
    assert body["expires_in"] == 300
    assert body["upload_headers"] == {"Content-Type": "application/pdf"}
    url = urlparse(body["upload_url"])
    signed = parse_qs(url.query)["X-Amz-SignedHeaders"][0].split(";")
    assert {"content-length", "content-type"} <= set(signed)
    key = key_of(attachment["id"], me.t)
    assert key.startswith(f"tenants/{me.t.tenant_id}/uploads/")
    assert key.endswith(".pdf")
    assert "photo" not in key  # no client text in storage keys
    assert unquote(url.path).endswith(key)


@pytest.mark.parametrize(
    ("start", "field", "message"),
    [
        ({"ctype": "text/html"}, "content_type", "Upload a PDF, JPEG, PNG or WebP file."),
        ({"size": 20 * 1024 * 1024 + 1}, "size_bytes", "Files can be at most 20 MB."),
        ({"size": -1}, "size_bytes", "The file is empty."),
        ({"filename": ""}, "filename", None),
    ],
)
def test_start_validates(
    s3: Any, me: Uploader, start: dict[str, Any], field: str, message: str | None
) -> None:
    response = me.start(**start)
    assert response.status_code == 422
    error = response.json()["errors"][0]
    assert error["field"] == field
    if message:
        assert error["message"] == message


def test_viewers_cannot_upload(s3: Any, tenant: TenantFixture) -> None:
    assert Uploader(tenant, "VIEWER").start().status_code == 403


# --- complete ------------------------------------------------------------------------


def test_upload_becomes_available_with_hash_and_download_link(
    s3: Any, me: Uploader, run: Any
) -> None:
    body = upload(s3, me, run)
    assert body["status"] == "AVAILABLE"
    link = urlparse(body["download_url"])
    disposition = parse_qs(link.query)["response-content-disposition"][0]
    assert disposition.startswith('inline; filename="bill.pdf"')
    with tenant_context(me.t.tenant_id, me.t.user_id):
        stored = Attachment.objects.get(pk=body["id"])
    assert stored.sha256 is not None
    assert bytes(stored.sha256) == hashlib.sha256(PDF).digest()
    # Completing again changes nothing.
    assert me.complete(body["id"]).json()["status"] == "AVAILABLE"


def test_complete_before_the_upload_is_a_conflict(s3: Any, me: Uploader) -> None:
    attachment_id = me.start().json()["attachment"]["id"]
    response = me.complete(attachment_id)
    assert (response.status_code, response.json()["code"]) == (409, "upload_missing")


@pytest.mark.parametrize(
    ("data", "ctype"),
    [(PNG + b"0" * (len(PDF) - len(PNG)), "application/pdf"), (PDF + b"extra", "application/pdf")],
    ids=["png-bytes-sent-as-pdf", "wrong-size"],
)
def test_a_file_that_is_not_what_was_announced_is_refused(
    s3: Any, me: Uploader, data: bytes, ctype: str
) -> None:
    attachment_id = me.start().json()["attachment"]["id"]
    key = key_of(attachment_id, me.t)
    put(s3, key, data, ctype)
    response = me.complete(attachment_id)
    assert (response.status_code, response.json()["code"]) == (422, "upload_mismatch")
    assert storage.head(key) is None  # deleted
    assert me.get(attachment_id).json()["status"] == "PENDING"  # never usable


def test_only_the_uploader_completes_but_every_member_can_read(
    s3: Any, me: Uploader, tenant: TenantFixture
) -> None:
    attachment_id = me.start().json()["attachment"]["id"]
    put(s3, key_of(attachment_id, me.t), PDF)
    colleague = Uploader(tenant, "ACCOUNTANT")
    assert colleague.complete(attachment_id).status_code == 404
    assert Uploader(tenant, "VIEWER").get(attachment_id).status_code == 200


# --- virus scan ----------------------------------------------------------------------


class FakeClamd(socketserver.BaseRequestHandler):
    """Speaks clamd's INSTREAM: finds EICAR, records what it was sent."""

    received: ClassVar[list[bytes]] = []

    def handle(self) -> None:
        sock = self.request
        command = b""
        while not command.endswith(b"\0"):
            command += sock.recv(1)
        assert command == b"zINSTREAM\0"
        data = b""
        while True:
            size = struct.unpack(">I", self._exactly(4))[0]
            if size == 0:
                break
            data += self._exactly(size)
        FakeClamd.received.append(data)
        verdict = b"Eicar-Test-Signature FOUND" if EICAR in data else b"OK"
        sock.sendall(b"stream: " + verdict + b"\0")

    def _exactly(self, n: int) -> bytes:
        out = b""
        while len(out) < n:
            out += self.request.recv(n - len(out))
        return out


@pytest.fixture
def clamd(settings: Any) -> Iterator[None]:
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), FakeClamd)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings.CLAMD_HOST, settings.CLAMD_PORT = "127.0.0.1", server.server_address[1]
    FakeClamd.received = []
    yield
    server.shutdown()
    server.server_close()


def test_scanned_clean_file_becomes_available(s3: Any, me: Uploader, run: Any, clamd: None) -> None:
    big = PDF + b"1" * 200_000  # several INSTREAM chunks
    assert upload(s3, me, run, data=big, size=len(big))["status"] == "AVAILABLE"
    assert FakeClamd.received == [big]


def test_infected_file_is_quarantined_and_deleted(
    s3: Any, me: Uploader, run: Any, clamd: None
) -> None:
    infected = PDF + EICAR
    body = upload(s3, me, run, data=infected, size=len(infected))
    assert body["status"] == "QUARANTINED"
    assert body["download_url"] is None
    assert storage.head(key_of(body["id"], me.t)) is None


def test_scanner_down_leaves_the_file_pending_for_a_retry(
    s3: Any, me: Uploader, settings: Any
) -> None:
    settings.CLAMD_HOST, settings.CLAMD_PORT = "127.0.0.1", 1
    attachment_id = me.start().json()["attachment"]["id"]
    put(s3, key_of(attachment_id, me.t), PDF)
    with (
        tenant_context(me.t.tenant_id, me.t.user_id),
        pytest.raises(scan.ScanError),
    ):
        services.process_upload(uuid.UUID(attachment_id))
    assert me.get(attachment_id).json()["status"] == "PENDING"


# --- use -----------------------------------------------------------------------------


def test_an_expense_links_only_an_available_upload(s3: Any, me: Uploader, run: Any) -> None:
    pending = me.start().json()["attachment"]["id"]
    available = upload(s3, me, run)["id"]

    def record(attachment_id: str) -> Any:
        body = {
            "category": "MATERIAL",
            "expense_date": "2026-10-20",
            "description": "Cement",
            "taxable_value": "100.00",
            "gst_amount": "18.00",
            "attachment_id": attachment_id,
        }
        return me.api.post(
            "/api/v1/expenses",
            body,
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
            **me.headers,
        )

    refused = record(pending)
    assert refused.status_code == 422
    assert refused.json()["errors"][0]["code"] == "not_available"
    assert record(available).status_code == 201


def test_download_names_are_safe_in_headers() -> None:
    value = storage.content_disposition('bill "final"\r\n₹.pdf')
    assert value.startswith('inline; filename="bill _final___')
    assert "\r" not in value
    assert "\n" not in value
    assert value.endswith("filename*=UTF-8''bill%20%22final%22%0D%0A%E2%82%B9.pdf")
