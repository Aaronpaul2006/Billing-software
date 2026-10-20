import logging
import uuid

from celery import shared_task
from django.db import connection, transaction

from apps.core.tenancy import tenant_context

from . import storage
from .services import process_upload

log = logging.getLogger(__name__)


@shared_task(  # type: ignore[untyped-decorator]  # celery has no type hints
    acks_late=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=8
)
def process_upload_task(tenant_id: str, user_id: str, attachment_id: str) -> str | None:
    """Retried with backoff while storage or the virus scanner is unreachable;
    the file stays PENDING (unusable) until it succeeds."""
    with tenant_context(tenant_id, user_id):
        return process_upload(uuid.UUID(attachment_id))


@shared_task  # type: ignore[untyped-decorator]  # celery has no type hints
def purge_stale_uploads(batch: int = 500) -> int:
    """Hourly (Celery beat): uploads still PENDING after a day. The rows go only
    if their objects could be deleted too (same transaction), so nothing is
    left behind in storage; a storage error leaves both for the next run."""
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SELECT purge_stale_uploads(%s)", [batch])
        keys = [row[0] for row in cursor.fetchall()]
        for key in keys:
            storage.delete(key)
    if keys:
        log.info("purged %s stale uploads", len(keys))
    return len(keys)
