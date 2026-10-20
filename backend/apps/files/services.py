"""User uploads (docs/02-api-design.md §7, docs/01-architecture.md §6 Files).

1. `start_upload`: an attachment row (PENDING) and a presigned PUT for exactly
   the declared type and size. The file goes from the client to storage
   directly, never through the API.
2. `complete_upload`: quick checks (it exists; size, type and first bytes
   match), then a task (`process_upload`) hashes and virus-scans it: AVAILABLE,
   or QUARANTINED with the object deleted.
3. Only AVAILABLE files can be linked (e.g. an expense's bill) or downloaded.
"""

import hashlib
import logging
import unicodedata
import uuid
from typing import Any

from django.db import transaction

from apps.core.errors import Conflict, DomainError, NotFound
from apps.core.permissions import require
from apps.core.queries import get_or_404
from apps.core.tenancy import Principal

from . import scan, storage
from .models import Attachment, AttachmentStatus

log = logging.getLogger(__name__)
security_log = logging.getLogger("security")

UPLOAD = "files.upload"

EXTENSIONS = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class UploadMismatch(DomainError):
    status = 422
    code = "upload_mismatch"
    detail = "The uploaded file is not the one announced. Upload it again."


def looks_like(content_type: str, head: bytes) -> bool:
    """Magic bytes: the file really is what its type says."""
    if content_type == "application/pdf":
        return head.startswith(b"%PDF-")
    if content_type == "image/jpeg":
        return head.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    return False


def clean_filename(name: str) -> str:
    """The name to show and offer on download: no path, no control characters."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(c for c in name if unicodedata.category(c)[0] != "C").strip()
    return name[:255] or "file"


def start_upload(
    principal: Principal, *, filename: str, content_type: str, size_bytes: int
) -> tuple[Attachment, str, dict[str, str]]:
    require(principal, UPLOAD)
    # The key holds no client text; the name lives only in the row.
    key = f"tenants/{principal.tenant_id}/uploads/{uuid.uuid7()}{EXTENSIONS[content_type]}"
    attachment = Attachment(
        storage_key=key,
        original_filename=clean_filename(filename),
        content_type=content_type,
        size_bytes=size_bytes,
        uploaded_by_id=principal.user_id,
    )
    attachment.save()
    url, headers = storage.upload_url(key, content_type, size_bytes)
    return attachment, url, headers


def get_attachment(principal: Principal, attachment_id: uuid.UUID) -> Attachment:
    require(principal, "tenant.read")
    return get_or_404(Attachment, attachment_id)


def complete_upload(principal: Principal, attachment_id: uuid.UUID) -> Attachment:
    require(principal, UPLOAD)
    attachment = get_or_404(Attachment, attachment_id)
    if attachment.uploaded_by_id != principal.user_id:
        raise NotFound  # another member's upload in progress is not yours to finish
    if attachment.status != AttachmentStatus.PENDING:
        return attachment  # already done: completing again is harmless
    stored = storage.head(attachment.storage_key)
    if stored is None:
        raise Conflict("The file has not been uploaded yet.", code="upload_missing")
    if (
        stored.size != attachment.size_bytes
        or stored.content_type != attachment.content_type
        or not looks_like(attachment.content_type, storage.get_range(attachment.storage_key, 16))
    ):
        storage.delete(attachment.storage_key)
        security_log.warning("upload_mismatch attachment=%s", attachment.pk)
        raise UploadMismatch

    from .tasks import process_upload_task

    tenant_id, user_id = str(principal.tenant_id), str(principal.user_id)
    transaction.on_commit(lambda: process_upload_task.delay(tenant_id, user_id, str(attachment.pk)))
    return attachment


def process_upload(attachment_id: uuid.UUID) -> str | None:
    """Hash and scan an uploaded file; AVAILABLE or QUARANTINED. Idempotent.
    Call inside tenant_context. A scanner failure raises (the task retries)."""
    attachment: Any = Attachment.objects.filter(pk=attachment_id).first()
    if attachment is None:
        return None
    if attachment.status != AttachmentStatus.PENDING:
        return str(attachment.status)
    data = storage.get(attachment.storage_key)
    problem = None
    if len(data) != attachment.size_bytes or not looks_like(attachment.content_type, data[:16]):
        problem = "content changed after upload"
    elif scan.enabled():
        found = scan.scan(data)
        problem = f"malware: {found}" if found else None
    else:
        log.warning("attachment %s not virus-scanned: CLAMD_HOST is not set", attachment.pk)
    if problem:
        storage.delete(attachment.storage_key)
        status = AttachmentStatus.QUARANTINED
        security_log.warning("upload_quarantined attachment=%s reason=%s", attachment.pk, problem)
    else:
        status = AttachmentStatus.AVAILABLE
    Attachment.objects.filter(pk=attachment.pk, status=AttachmentStatus.PENDING).update(
        status=status, sha256=hashlib.sha256(data).digest()
    )
    return str(status)
