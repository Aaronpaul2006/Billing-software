"""Proof of work (Part B): site diary photos chosen to go with a bill.

Staff choose them (those who draft bills); the client sees them with the bill
in the portal (db/schema.sql lets a portal session read exactly those photos).
"""

import uuid
from typing import Any

from django.db import transaction

from apps.core.errors import Conflict, Invalid
from apps.core.permissions import require
from apps.core.queries import get_or_404
from apps.core.tenancy import Principal
from apps.documents.models import Document
from apps.documents.services.pdfs import enqueue_pdf
from apps.files import storage

from .models import DiaryPhoto, DocumentPhoto

CHOOSE = "documents.draft"
MAX = 40


def photos(document: Document) -> list[dict[str, Any]]:
    """The bill's photos, in the order chosen, ready to show."""
    rows = (
        DocumentPhoto.objects.filter(document=document)
        .select_related("diary_photo__entry", "diary_photo__attachment")
        .order_by("sort_order")
    )
    out = []
    for row in rows:
        p = row.diary_photo
        out.append(
            {
                "id": p.pk,
                "caption": p.caption,
                "entry_date": p.entry.entry_date,
                "url": storage.download_url(
                    p.attachment.storage_key, p.attachment.original_filename
                ),
            }
        )
    return out


def choose(principal: Principal, document_id: uuid.UUID, photo_ids: list[uuid.UUID]) -> Document:
    """Replace the bill's photos with these, in this order."""
    require(principal, CHOOSE)
    if len(photo_ids) > MAX:
        raise Invalid("diary_photo_ids", f"At most {MAX} photos a bill.", code="too_many_photos")
    if len(set(photo_ids)) != len(photo_ids):
        raise Invalid("diary_photo_ids", "A photo is listed twice.", code="duplicate")
    with transaction.atomic():
        doc = get_or_404(Document, document_id, for_update=True)
        if doc.status == "CANCELLED":
            raise Conflict("This bill is cancelled.", code="document_cancelled")
        if doc.project_id is None:
            raise Conflict("This bill has no project, so no site diary.", code="no_project")
        found = {
            p.pk: p for p in DiaryPhoto.objects.filter(pk__in=photo_ids).select_related("entry")
        }
        for i, pid in enumerate(photo_ids):
            photo = found.get(pid)
            if photo is None or photo.entry.project_id != doc.project_id:
                raise Invalid(
                    f"diary_photo_ids[{i}]",
                    "Not a photo from this project's site diary.",
                    code="not_found",
                )
        DocumentPhoto.objects.filter(document=doc).delete()
        DocumentPhoto.objects.bulk_create(
            [
                DocumentPhoto(
                    tenant_id=principal.tenant_id,  # bulk_create skips save(): set it here
                    document=doc,
                    diary_photo_id=pid,
                    sort_order=i,
                    created_by_id=principal.user_id,
                )
                for i, pid in enumerate(photo_ids)
            ]
        )
        # the stored PDF shows the old photos: make it again
        if doc.pdf_attachment_id and doc.status != "DRAFT":
            Document.objects.filter(pk=doc.pk).update(pdf_attachment_id=None)
            enqueue_pdf(principal.tenant_id, principal.user_id, doc.pk)
    return doc
