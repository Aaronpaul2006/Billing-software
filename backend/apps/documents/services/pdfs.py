"""Rendering and storing document PDFs."""

import hashlib
import uuid

from django.db import transaction

from apps.files import storage
from apps.files.models import Attachment

from ..models import Document
from ..pdf.render import render_pdf


def pdf_filename(doc: Document) -> str:
    name = (doc.doc_number or "draft").replace("/", "-")
    suffix = "-cancelled" if doc.status == "CANCELLED" else ""
    return f"{doc.doc_type.lower()}-{name}{suffix}.pdf"


def store_pdf(document_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID | None:
    """Render an issued document once, upload it, link it. Idempotent: a
    document that already has its PDF is left alone. Call inside tenant_context."""
    with transaction.atomic():
        doc = Document.objects.select_for_update().filter(pk=document_id).first()
        if doc is None or doc.status == "DRAFT":
            return None
        if doc.pdf_attachment_id:
            existing: uuid.UUID = doc.pdf_attachment_id
            return existing
        pdf = render_pdf(doc)
        key = storage.new_key(doc.tenant_id, "documents", pdf_filename(doc))
        storage.put(key, pdf, "application/pdf")
        attachment = Attachment(
            storage_key=key,
            original_filename=pdf_filename(doc),
            content_type="application/pdf",
            size_bytes=len(pdf),
            sha256=hashlib.sha256(pdf).digest(),
            status="AVAILABLE",
            uploaded_by_id=user_id,
        )
        attachment.save()
        Document.objects.filter(pk=doc.pk).update(pdf_attachment_id=attachment.pk)
        return attachment.pk


def enqueue_pdf(tenant_id: uuid.UUID, user_id: uuid.UUID, document_id: uuid.UUID) -> None:
    """Queue rendering once the current transaction commits (never for a
    rolled-back issue)."""
    from ..tasks import render_document_pdf

    transaction.on_commit(
        lambda: render_document_pdf.delay(str(tenant_id), str(user_id), str(document_id))
    )
