import logging

from celery import shared_task
from django.db import connection

log = logging.getLogger(__name__)


@shared_task  # type: ignore[untyped-decorator]  # celery has no type hints
def purge_idempotency_keys() -> int:
    """Hourly (Celery beat): stored replies past their 24 hours. Runs without a
    tenant: the database function sees only expired keys (db/schema.sql §8)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT purge_expired_idempotency_keys()")
        purged = int(cursor.fetchone()[0])
    if purged:
        log.info("purged %s expired idempotency keys", purged)
    return purged
