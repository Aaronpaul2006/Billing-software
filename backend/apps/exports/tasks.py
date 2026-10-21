import logging
import uuid

from celery import shared_task
from django.db import connection, transaction

from apps.core.tenancy import tenant_context
from apps.files import storage

from .services import run_export

log = logging.getLogger(__name__)


@shared_task(  # type: ignore[untyped-decorator]  # celery has no type hints
    acks_late=True, autoretry_for=(OSError,), retry_backoff=True, max_retries=3
)
def run_export_task(tenant_id: str, user_id: str, export_id: str) -> str | None:
    """Storage briefly unreachable: retried; any other failure marks it FAILED."""
    with tenant_context(tenant_id, user_id):
        return run_export(uuid.UUID(export_id))


@shared_task  # type: ignore[untyped-decorator]  # celery has no type hints
def purge_old_exports(batch: int = 500) -> int:
    """Hourly (Celery beat): exports older than 7 days, rows and files together."""
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SELECT purge_old_exports(%s)", [batch])
        keys = [row[0] for row in cursor.fetchall()]
        for key in keys:
            storage.delete(key)
    if keys:
        log.info("purged %s old exports", len(keys))
    return len(keys)
