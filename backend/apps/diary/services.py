"""Site diary (Part B): one entry per project and day, with photos.

Whoever records site entries (site engineers and up) writes it; every member
reads it. Photos are image attachments that passed the virus check (the
database insists too, 7e).
"""

import uuid
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Max

from apps.core.errors import Conflict, Invalid
from apps.core.permissions import require
from apps.core.queries import get_or_404, get_or_invalid
from apps.core.tenancy import Principal
from apps.core.versioning import update_versioned
from apps.files.models import Attachment
from apps.projects.models import Project

from .models import DiaryEntry, DiaryPhoto

WRITE = "expenses.record"  # the roles that record site entries
MAX_PHOTOS = 30


def _photo(field: str, attachment_id: uuid.UUID) -> Attachment:
    attachment = get_or_invalid(Attachment, attachment_id, field, label="photo")
    if attachment.status != "AVAILABLE":
        raise Invalid(
            field, "The photo is still being checked; wait a moment.", code="not_available"
        )
    if not attachment.content_type.startswith("image/"):
        raise Invalid(field, "Only photos (JPEG, PNG or WebP) go in the diary.", code="not_a_photo")
    return attachment


def _add_photos(principal: Principal, entry: DiaryEntry, photos: list[dict[str, Any]]) -> None:
    start = (DiaryPhoto.objects.filter(entry=entry).aggregate(n=Max("sort_order"))["n"] or 0) + 1
    if DiaryPhoto.objects.filter(entry=entry).count() + len(photos) > MAX_PHOTOS:
        raise Invalid("photos", f"At most {MAX_PHOTOS} photos a day.", code="too_many_photos")
    for i, photo in enumerate(photos):
        _photo(f"photos[{i}].attachment_id", photo["attachment_id"])
        if DiaryPhoto.objects.filter(entry=entry, attachment_id=photo["attachment_id"]).exists():
            continue
        DiaryPhoto(
            entry=entry,
            attachment_id=photo["attachment_id"],
            caption=(photo.get("caption") or "").strip() or None,
            sort_order=start + i,
            created_by_id=principal.user_id,
        ).save()


def record(principal: Principal, project_id: uuid.UUID, data: dict[str, Any]) -> DiaryEntry:
    """The day's entry; a second one for the same day is refused (edit it)."""
    require(principal, WRITE)
    project = get_or_404(Project, project_id)
    photos = data.pop("photos", None) or []
    existing = DiaryEntry.objects.filter(project=project, entry_date=data["entry_date"]).first()
    if existing is not None:
        raise Conflict(
            "This day already has an entry; add to it instead.",
            code="entry_exists",
            extra={"entry_id": str(existing.pk)},
        )
    try:
        with transaction.atomic():
            entry = DiaryEntry(**data, project=project, created_by_id=principal.user_id)
            entry.save()
            _add_photos(principal, entry, photos)
    except IntegrityError as exc:  # written by someone else a moment ago
        raise Conflict(
            "This day already has an entry; add to it instead.", code="entry_exists"
        ) from exc
    return get_or_404(DiaryEntry, entry.pk)


def update(
    principal: Principal, entry_id: uuid.UUID, expected: int, changes: dict[str, Any]
) -> DiaryEntry:
    require(principal, WRITE)
    changes.pop("photos", None)
    changes.pop("entry_date", None)  # a day stays its day
    with transaction.atomic():
        entry = get_or_404(DiaryEntry, entry_id, for_update=True)
        update_versioned(DiaryEntry.objects, entry.pk, expected, **changes)
    return get_or_404(DiaryEntry, entry_id)


def add_photos(
    principal: Principal, entry_id: uuid.UUID, photos: list[dict[str, Any]]
) -> DiaryEntry:
    require(principal, WRITE)
    with transaction.atomic():
        entry = get_or_404(DiaryEntry, entry_id, for_update=True)
        _add_photos(principal, entry, photos)
    return get_or_404(DiaryEntry, entry_id)


def remove_photo(principal: Principal, photo_id: uuid.UUID) -> None:
    require(principal, WRITE)
    photo = get_or_404(DiaryPhoto, photo_id)
    photo.delete()
