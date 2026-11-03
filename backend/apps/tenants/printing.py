"""Print settings (B.12): how the business's bills look on paper.

One row per business, made on the first save; until then everyone sees the
defaults (detailed layout, nothing else set) at version 1, so the first save
sends `If-Match: "v1"` like any other.
"""

import uuid
from typing import Any

from django.db import transaction

from apps.core.errors import Invalid
from apps.core.permissions import require
from apps.core.queries import get_or_invalid
from apps.core.tenancy import Principal
from apps.core.versioning import update_versioned
from apps.files.models import Attachment

from .models import PrintSettings

IMAGE_TYPES = frozenset({"image/png", "image/jpeg"})  # what the PDF renderer prints reliably
MAX_IMAGE_BYTES = 1024 * 1024  # a logo or a signature: small, so every PDF stays small

FIELDS = (
    "layout",
    "logo_attachment_id",
    "signature_attachment_id",
    "bank_account_name",
    "bank_name",
    "bank_account_number",
    "bank_ifsc",
    "bank_branch",
    "upi_id",
    "default_terms",
)


def current(tenant_id: uuid.UUID) -> PrintSettings:
    """The saved settings, or the defaults (not saved). Inside tenant context."""
    found = PrintSettings.objects.filter(tenant_id=tenant_id).first()
    return found if found is not None else PrintSettings(tenant_id=tenant_id)


def get_print_settings(principal: Principal) -> PrintSettings:
    require(principal, "tenant.read")
    return current(principal.tenant_id)


def _image(field: str, attachment_id: uuid.UUID) -> None:
    attachment = get_or_invalid(Attachment, attachment_id, field, label="attachment")
    if attachment.status != "AVAILABLE":
        raise Invalid(field, "The file is not available.", code="not_available")
    if attachment.content_type not in IMAGE_TYPES:
        raise Invalid(field, "Choose a PNG or JPEG image.", code="not_an_image")
    if attachment.size_bytes > MAX_IMAGE_BYTES:
        raise Invalid(field, "The image can be at most 1 MB.", code="image_too_large")


def update_print_settings(
    principal: Principal, expected: int, changes: dict[str, Any]
) -> PrintSettings:
    require(principal, "tenant.settings")
    for field in ("logo_attachment_id", "signature_attachment_id"):
        if changes.get(field):
            _image(field, changes[field])
    with transaction.atomic():
        row, _ = PrintSettings.objects.get_or_create(tenant_id=principal.tenant_id)
        update_versioned(PrintSettings.objects, row.pk, expected, **changes)
    return current(principal.tenant_id)


def default_terms(tenant_id: uuid.UUID) -> str | None:
    found = PrintSettings.objects.filter(tenant_id=tenant_id).values_list(
        "default_terms", flat=True
    )
    return next(iter(found), None)


def snapshot(tenant_id: uuid.UUID) -> dict[str, Any]:
    """The settings as frozen into a bill when it is issued, so a reprint
    looks like the original even after the settings change."""
    s = current(tenant_id)
    return {
        "layout": s.layout,
        "logo_attachment_id": str(s.logo_attachment_id) if s.logo_attachment_id else None,
        "signature_attachment_id": (
            str(s.signature_attachment_id) if s.signature_attachment_id else None
        ),
        "bank_account_name": s.bank_account_name,
        "bank_name": s.bank_name,
        "bank_account_number": s.bank_account_number,
        "bank_ifsc": s.bank_ifsc,
        "bank_branch": s.bank_branch,
        "upi_id": s.upi_id,
    }
