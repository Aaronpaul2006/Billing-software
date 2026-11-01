"""Exports (docs/02-api-design.md §8): requested here, written by a task.

The request is checked and stored as PENDING; after commit a Celery task
builds the file inside the tenant's context, puts it in object storage and
marks the export READY (or FAILED with a message the user can act on).
"""

import logging
import uuid
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.core.errors import NotFound
from apps.core.permissions import require
from apps.core.queries import get_or_404
from apps.core.tenancy import Principal
from apps.files import storage

from . import builders, gstr1, statement_pdf, writers
from .models import Export, ExportStatus

log = logging.getLogger(__name__)

EXPORT = "reports.view"  # exports show what reports show
RECENT = 20


def request_export(
    principal: Principal, *, kind: str, file_format: str, params: dict[str, Any]
) -> Export:
    require(principal, EXPORT)
    export = Export(kind=kind, format=file_format, params=params, requested_by_id=principal.user_id)
    export.save()
    from .tasks import run_export_task

    tenant_id, user_id = str(principal.tenant_id), str(principal.user_id)
    transaction.on_commit(lambda: run_export_task.delay(tenant_id, user_id, str(export.pk)))
    return export


def recent_exports(principal: Principal) -> list[Export]:
    """The caller's own latest exports (files are kept 7 days)."""
    require(principal, EXPORT)
    return list(
        Export.objects.filter(requested_by_id=principal.user_id).order_by("-created_at")[:RECENT]
    )


def get_export(principal: Principal, export_id: uuid.UUID) -> Export:
    require(principal, EXPORT)
    export = get_or_404(Export, export_id)
    if export.requested_by_id != principal.user_id:
        raise NotFound  # another member's file: theirs to download
    return export


def build(export: Export) -> tuple[bytes, str, int, list[str]]:
    """(file bytes, file name, row count, warnings). Call inside tenant_context."""
    if export.kind == "GSTR1":
        return gstr1.build_gstr1(export.tenant_id, export.params)
    if export.format == "PDF":
        return statement_pdf.render(export.tenant_id, export.params)
    built = builders.BUILDERS[export.kind](export.tenant_id, export.params)
    body = writers.write(built.table, export.format)
    name = f"{built.stem}.{writers.EXTENSIONS[export.format]}"
    return body, name, len(built.table.rows), built.warnings


def run_export(export_id: uuid.UUID) -> str | None:
    """Build, store and mark READY / FAILED. Idempotent. Call inside tenant_context."""
    export = Export.objects.filter(pk=export_id).first()
    if export is None:
        return None
    if export.status != ExportStatus.PENDING:
        return str(export.status)
    try:
        body, name, count, warnings = build(export)
    except (builders.TooManyRows, gstr1.Gstr1Error) as exc:
        return _fail(export, str(exc))
    except Exception:
        log.exception("export %s failed", export.pk)
        return _fail(export, "The file could not be made. Try again, or tell support.")
    key = f"tenants/{export.tenant_id}/exports/{uuid.uuid7()}.{writers.EXTENSIONS[export.format]}"
    storage.put(key, body, writers.CONTENT_TYPES[export.format])
    Export.objects.filter(pk=export.pk, status=ExportStatus.PENDING).update(
        status=ExportStatus.READY,
        file_name=name,
        storage_key=key,
        size_bytes=len(body),
        row_count=count,
        warnings=warnings,
        finished_at=timezone.now(),
    )
    return str(ExportStatus.READY)


def _fail(export: Export, message: str) -> str:
    Export.objects.filter(pk=export.pk, status=ExportStatus.PENDING).update(
        status=ExportStatus.FAILED, error=message[:1000], finished_at=timezone.now()
    )
    return str(ExportStatus.FAILED)


def download_url(export: Export) -> str | None:
    if export.status != ExportStatus.READY or not export.storage_key or not export.file_name:
        return None
    return storage.download_url(export.storage_key, export.file_name, disposition="attachment")
